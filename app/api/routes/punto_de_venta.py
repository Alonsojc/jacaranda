"""Rutas de punto de venta (POS)."""

from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission, require_role
from app.models.usuario import RolUsuario, Usuario
from app.models.venta import CorteCaja
from app.models.gasto_fijo import GastoFijo
from app.services.auditoria_service import registrar_evento
from app.schemas.venta import (
    VentaCreate, VentaResponse, TicketResponse, CorteCajaCreate, CorteCajaResponse,
    CorteCajaResumen,
)
from app.services import venta_service as svc

router = APIRouter()


# --- Schemas inline para gastos fijos ---
class GastoFijoCreate(BaseModel):
    concepto: str
    monto: Decimal
    periodicidad: str = "mensual"
    dia_pago: int | None = None
    notas: str | None = None


class GastoFijoResponse(BaseModel):
    id: int
    concepto: str
    monto: Decimal
    periodicidad: str
    dia_pago: int | None
    notas: str | None
    activo: bool
    model_config = {"from_attributes": True}


@router.post("/ventas", response_model=VentaResponse, status_code=201)
def crear_venta(
    data: VentaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("pos", "editar")),
):
    try:
        return svc.procesar_venta(db, data, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ventas", response_model=list[VentaResponse])
def listar_ventas(
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("pos", "ver")),
):
    return svc.listar_ventas(db, fecha_inicio, fecha_fin, limit)


@router.get("/ventas/{id}", response_model=VentaResponse)
def obtener_venta(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("pos", "ver")),
):
    try:
        return svc.obtener_venta(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/ventas/{id}/ticket")
def obtener_ticket(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("pos", "ver")),
):
    try:
        return svc.generar_ticket(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/ventas/{id}/ticket/pdf")
def ticket_pdf(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("pos", "ver")),
):
    """Descarga ticket de venta en PDF."""
    from app.services import pdf_service
    try:
        ticket_data = svc.generar_ticket(db, id)
        buf = pdf_service.generar_ticket_pdf(ticket_data)
        return StreamingResponse(
            buf, media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=ticket_{ticket_data['folio']}.pdf"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/ventas/{id}/cancelar", response_model=VentaResponse)
def cancelar_venta(
    id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("pos", "cancelar venta")),
):
    try:
        return svc.cancelar_venta(db, id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Corte de caja ---

@router.post("/corte-caja", response_model=CorteCajaResponse, status_code=201)
def realizar_corte(
    data: CorteCajaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("corte", "editar")),
):
    if data.permitir_repetir and user.rol != RolUsuario.ADMINISTRADOR:
        raise HTTPException(status_code=403, detail="Solo administrador puede repetir un corte")
    try:
        return svc.realizar_corte_caja(db, data, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/corte-caja/resumen", response_model=CorteCajaResumen)
def resumen_corte(
    fecha: date | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("corte", "ver")),
):
    return svc.resumen_corte_caja(db, fecha)


@router.get("/cortes-caja", response_model=list[CorteCajaResponse])
def historial_cortes(
    limit: int = Query(default=30, le=100),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("corte", "ver")),
):
    """Historial de cortes de caja."""
    return db.query(CorteCaja).order_by(desc(CorteCaja.fecha)).limit(limit).all()


# --- Gastos fijos ---

@router.get("/gastos-fijos", response_model=list[GastoFijoResponse])
def listar_gastos_fijos(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    return db.query(GastoFijo).filter(GastoFijo.activo.is_(True)).offset(skip).limit(limit).all()


@router.get("/gastos-fijos/inactivos", response_model=list[GastoFijoResponse])
def listar_gastos_fijos_inactivos(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("papelera", "ver")),
):
    return db.query(GastoFijo).filter(GastoFijo.activo.is_(False)).offset(skip).limit(limit).all()


@router.post("/gastos-fijos", response_model=GastoFijoResponse, status_code=201)
def crear_gasto_fijo(
    data: GastoFijoCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    gasto = GastoFijo(**data.model_dump())
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto


@router.put("/gastos-fijos/{id}", response_model=GastoFijoResponse)
def actualizar_gasto_fijo(
    id: int,
    data: GastoFijoCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_admin_or_override("corte", "editar gasto fijo")),
):
    gasto = db.query(GastoFijo).filter(GastoFijo.id == id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    _ALLOWED_FIELDS = {"concepto", "monto", "periodicidad", "dia_pago", "notas"}
    for key, value in data.model_dump().items():
        if key not in _ALLOWED_FIELDS:
            continue
        setattr(gasto, key, value)
    db.commit()
    db.refresh(gasto)
    return gasto


@router.delete("/gastos-fijos/{id}")
def eliminar_gasto_fijo(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_admin_or_override("corte", "desactivar gasto fijo")),
):
    gasto = db.query(GastoFijo).filter(GastoFijo.id == id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    gasto.activo = False
    db.commit()
    return {"ok": True}


@router.post("/gastos-fijos/{id}/reactivar", response_model=GastoFijoResponse)
def reactivar_gasto_fijo(
    id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("papelera", "reactivar gasto fijo")),
):
    gasto = db.query(GastoFijo).filter(GastoFijo.id == id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    if gasto.activo:
        raise HTTPException(status_code=400, detail="El gasto ya está activo")
    gasto.activo = True
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="actualizar",
        modulo="papelera",
        entidad="gasto_fijo",
        entidad_id=id,
        datos_anteriores={"activo": False},
        datos_nuevos={"activo": True, "accion": "reactivar gasto fijo"},
        commit=False,
    )
    db.commit()
    db.refresh(gasto)
    return gasto
