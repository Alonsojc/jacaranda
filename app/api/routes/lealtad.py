"""Rutas del sistema de lealtad avanzado."""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.models.lealtad import TipoCupon, NivelLealtad, HistorialPuntos
from app.services import lealtad_service

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────

class CuponCreate(BaseModel):
    codigo: str = Field(..., max_length=30)
    nombre: str = Field(..., max_length=200)
    descripcion: str | None = None
    tipo: TipoCupon
    valor: Decimal
    producto_id: int | None = None
    compra_minima: Decimal = Decimal("0")
    nivel_requerido: NivelLealtad | None = None
    max_usos: int = 1
    fecha_inicio: date
    fecha_fin: date


class CuponValidar(BaseModel):
    codigo: str
    cliente_id: int | None = None
    monto_compra: Decimal = Decimal("0")


class CuponCanjear(BaseModel):
    codigo: str
    cliente_id: int
    venta_id: int


class AsignarCuponBody(BaseModel):
    cupon_id: int
    cliente_id: int


# ── Niveles ──────────────────────────────────────────────────────────

@router.get("/niveles")
def obtener_niveles(_user: Usuario = Depends(get_current_user)):
    """Retorna los niveles de lealtad con umbrales y beneficios."""
    return {
        "niveles": [
            {
                "nivel": NivelLealtad.BRONCE.value,
                "puntos_min": 0,
                "puntos_max": 499,
                "multiplicador": 1.0,
                "beneficios": "Acumulacion base de puntos",
            },
            {
                "nivel": NivelLealtad.PLATA.value,
                "puntos_min": 500,
                "puntos_max": 1499,
                "multiplicador": 1.5,
                "beneficios": "1.5x puntos en cada compra",
            },
            {
                "nivel": NivelLealtad.ORO.value,
                "puntos_min": 1500,
                "puntos_max": None,
                "multiplicador": 2.0,
                "beneficios": "2x puntos en cada compra + acceso a cupones exclusivos",
            },
        ]
    }


# ── Tarjeta digital ─────────────────────────────────────────────────

@router.get("/tarjeta/{cliente_id}")
def obtener_tarjeta(
    cliente_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Obtiene los datos de la tarjeta de lealtad digital de un cliente."""
    try:
        tarjeta = lealtad_service.obtener_tarjeta(db, cliente_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Generar QR si no tiene
    if not tarjeta["tarjeta_qr"]:
        tarjeta = lealtad_service.generar_tarjeta_qr(db, cliente_id)
        db.commit()
        tarjeta = lealtad_service.obtener_tarjeta(db, cliente_id)

    return tarjeta


@router.get("/tarjeta-qr/{qr_code}")
def buscar_por_qr(
    qr_code: str,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Busca un cliente por codigo QR (para uso en POS)."""
    cliente = lealtad_service.buscar_por_qr(db, qr_code)
    if not cliente:
        raise HTTPException(status_code=404, detail="Tarjeta QR no encontrada")
    return {
        "cliente_id": cliente.id,
        "nombre": cliente.nombre,
        "nivel": cliente.nivel_lealtad,
        "puntos_acumulados": cliente.puntos_acumulados,
    }


# ── Cupones ──────────────────────────────────────────────────────────

@router.post("/cupones", status_code=201)
def crear_cupon(
    data: CuponCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    """Crea un nuevo cupon (solo ADMIN/GERENTE)."""
    cupon = lealtad_service.crear_cupon(db, data.model_dump())
    db.commit()
    db.refresh(cupon)
    return {
        "id": cupon.id,
        "codigo": cupon.codigo,
        "nombre": cupon.nombre,
        "tipo": cupon.tipo.value,
        "valor": float(cupon.valor),
        "fecha_inicio": str(cupon.fecha_inicio),
        "fecha_fin": str(cupon.fecha_fin),
    }


@router.get("/cupones")
def listar_cupones(
    activos_only: bool = Query(default=True, description="Solo cupones activos y vigentes"),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Lista cupones disponibles."""
    cupones = lealtad_service.listar_cupones(db, activos_only=activos_only)
    return [
        {
            "id": c.id,
            "codigo": c.codigo,
            "nombre": c.nombre,
            "tipo": c.tipo.value,
            "valor": float(c.valor),
            "compra_minima": float(c.compra_minima),
            "nivel_requerido": c.nivel_requerido.value if c.nivel_requerido else None,
            "max_usos": c.max_usos,
            "usos_actuales": c.usos_actuales,
            "fecha_inicio": str(c.fecha_inicio),
            "fecha_fin": str(c.fecha_fin),
            "estado": c.estado.value,
        }
        for c in cupones
    ]


@router.post("/cupones/validar")
def validar_cupon(
    data: CuponValidar,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Valida si un cupon es aplicable."""
    resultado = lealtad_service.validar_cupon(
        db,
        codigo=data.codigo,
        cliente_id=data.cliente_id,
        monto_compra=data.monto_compra,
    )
    return resultado


@router.post("/cupones/canjear")
def canjear_cupon(
    data: CuponCanjear,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Canjea un cupon en una venta."""
    # Primero validar
    validacion = lealtad_service.validar_cupon(
        db, codigo=data.codigo, cliente_id=data.cliente_id,
    )
    if not validacion["valid"]:
        raise HTTPException(status_code=400, detail=validacion["reason"])

    try:
        registro = lealtad_service.canjear_cupon(
            db, data.codigo, data.cliente_id, data.venta_id,
        )
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"mensaje": "Cupon canjeado exitosamente", "cupon_cliente_id": registro.id}


# ── Cumpleanos ───────────────────────────────────────────────────────

@router.get("/cumpleanos")
def cumpleanos_del_mes(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Lista clientes que cumplen anos este mes."""
    clientes = lealtad_service.cumpleanos_del_mes(db)
    return [
        {
            "id": c.id,
            "nombre": c.nombre,
            "fecha_cumpleanos": str(c.fecha_cumpleanos),
            "nivel": c.nivel_lealtad,
        }
        for c in clientes
    ]


@router.post("/cumpleanos/enviar-ofertas")
def enviar_ofertas_cumpleanos(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    """Genera cupones de cumpleanos para clientes del mes."""
    resultados = lealtad_service.enviar_ofertas_cumpleanos(db)
    db.commit()
    return {
        "mensaje": f"Se generaron {len(resultados)} cupones de cumpleanos",
        "cupones": resultados,
    }


# ── Dashboard ────────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard_lealtad(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Estadisticas del programa de lealtad."""
    return lealtad_service.dashboard_lealtad(db)


# ── Historial ────────────────────────────────────────────────────────

@router.get("/historial/{cliente_id}")
def historial_puntos(
    cliente_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Historial de movimientos de puntos de un cliente."""
    registros = (
        db.query(HistorialPuntos)
        .filter(HistorialPuntos.cliente_id == cliente_id)
        .order_by(HistorialPuntos.creado_en.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "puntos": r.puntos,
            "concepto": r.concepto,
            "venta_id": r.venta_id,
            "saldo_anterior": r.saldo_anterior,
            "saldo_nuevo": r.saldo_nuevo,
            "fecha": r.creado_en.isoformat() if r.creado_en else None,
        }
        for r in registros
    ]
