"""Rutas de contabilidad: catálogo de cuentas, pólizas, balance, estado de resultados, conciliación."""

from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import contabilidad_service as svc
from app.services import excel_service

router = APIRouter()


# --- Schemas ---

class CuentaCreate(BaseModel):
    codigo: str
    nombre: str
    tipo: str
    naturaleza: str
    nivel: int = 3
    padre_id: int | None = None


class CuentaResponse(BaseModel):
    id: int
    codigo: str
    nombre: str
    tipo: str
    naturaleza: str
    nivel: int
    padre_id: int | None
    model_config = {"from_attributes": True}


class LineaAsientoInput(BaseModel):
    cuenta_codigo: str
    debe: Decimal = Decimal("0")
    haber: Decimal = Decimal("0")
    concepto: str | None = None


class AsientoCreate(BaseModel):
    fecha: date
    concepto: str
    tipo: str = "diario"
    lineas: list[LineaAsientoInput]
    referencia_id: int | None = None
    referencia_tipo: str | None = None


class MovBancarioCreate(BaseModel):
    fecha: date
    concepto: str
    referencia: str | None = None
    deposito: Decimal = Decimal("0")
    retiro: Decimal = Decimal("0")
    saldo: Decimal = Decimal("0")
    notas: str | None = None


# --- Catálogo de cuentas ---

@router.get("/cuentas")
def catalogo_cuentas(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    return svc.catalogo_cuentas(db)


@router.post("/cuentas", status_code=201)
def crear_cuenta(
    data: CuentaCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    try:
        cuenta = svc.crear_cuenta(db, data.model_dump())
        return {"id": cuenta.id, "codigo": cuenta.codigo, "nombre": cuenta.nombre}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cuentas/seed")
def seedear_catalogo(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    """Siembra catálogo de cuentas por defecto."""
    n = svc.seedear_catalogo(db)
    return {"cuentas_creadas": n}


# --- Asientos contables ---

@router.post("/asientos", status_code=201)
def crear_asiento(
    data: AsientoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    try:
        lineas = [l.model_dump() for l in data.lineas]
        asiento = svc.crear_asiento(
            db, data.fecha, data.concepto, data.tipo, lineas,
            user.id, data.referencia_id, data.referencia_tipo,
        )
        return {
            "id": asiento.id, "numero": asiento.numero,
            "concepto": asiento.concepto, "fecha": asiento.fecha.isoformat(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/libro-diario")
def libro_diario(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    return svc.libro_diario(db, fecha_inicio, fecha_fin)


# --- Balance general ---

@router.get("/balance-general")
def balance_general(
    fecha_corte: date | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    return svc.balance_general(db, fecha_corte)


# --- Estado de resultados ---

@router.get("/estado-resultados")
def estado_resultados(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    return svc.estado_resultados(db, fecha_inicio, fecha_fin)


# --- Conciliación bancaria ---

@router.post("/banco/movimientos", status_code=201)
def registrar_movimiento(
    data: MovBancarioCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    mov = svc.registrar_movimiento_banco(db, data.model_dump())
    return {
        "id": mov.id, "fecha": mov.fecha.isoformat(),
        "concepto": mov.concepto, "deposito": float(mov.deposito),
        "retiro": float(mov.retiro),
    }


@router.get("/banco/conciliacion")
def conciliacion_bancaria(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    return svc.conciliacion_bancaria(db, mes, anio)


@router.post("/banco/movimientos/{id}/conciliar")
def conciliar_movimiento(
    id: int,
    venta_id: int | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    try:
        mov = svc.conciliar_movimiento(db, id, venta_id)
        return {"ok": True, "id": mov.id, "conciliado": mov.conciliado}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Exportaciones Excel ─────────────────────────────────────────

@router.get("/reporte-mensual/excel")
def reporte_mensual_excel(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    """Descarga reporte mensual consolidado (Estado de Resultados + Balance General + Polizas)."""
    buf = excel_service.exportar_reporte_mensual(db, mes, anio)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=reporte_mensual_{anio}_{mes:02d}.xlsx"
        },
    )


@router.get("/balance-general/excel")
def balance_general_excel(
    fecha_corte: date | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    """Descarga balance general en Excel."""
    buf = excel_service.exportar_balance_general(db, fecha_corte)
    corte = (fecha_corte or date.today()).isoformat()
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=balance_general_{corte}.xlsx"},
    )


@router.get("/estado-resultados/excel")
def estado_resultados_excel(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    """Descarga estado de resultados en Excel."""
    buf = excel_service.exportar_estado_resultados(db, fecha_inicio, fecha_fin)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=estado_resultados_{fecha_inicio}_{fecha_fin}.xlsx"},
    )


@router.get("/libro-diario/excel")
def libro_diario_excel(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    """Descarga pólizas contables (libro diario) en Excel."""
    buf = excel_service.exportar_polizas(db, fecha_inicio, fecha_fin)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=polizas_{fecha_inicio}_{fecha_fin}.xlsx"},
    )
