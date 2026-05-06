"""Rutas de gestión de proveedores y compras."""

from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.services import compras_service as svc

router = APIRouter()


# --- Schemas ---

class ItemOrdenCompra(BaseModel):
    ingrediente_id: int = Field(..., gt=0)
    cantidad: Decimal = Field(..., gt=0)
    precio_unitario: Decimal = Field(..., ge=0)
    notas: str | None = None


class OrdenCompraCreate(BaseModel):
    proveedor_id: int = Field(..., gt=0)
    sucursal_id: int | None = Field(default=None, gt=0)
    fecha_entrega_esperada: date | None = None
    notas: str | None = None
    items: list[ItemOrdenCompra]


class ItemRecibido(BaseModel):
    detalle_id: int = Field(..., gt=0)
    cantidad_recibida: Decimal = Field(..., gt=0)


class RecepcionOrden(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=80)
    items: list[ItemRecibido]


class CuentaPagarCreate(BaseModel):
    proveedor_id: int = Field(..., gt=0)
    orden_compra_id: int | None = Field(default=None, gt=0)
    concepto: str = Field(..., min_length=1, max_length=300)
    monto_total: Decimal = Field(..., gt=0)
    fecha_factura: date
    fecha_vencimiento: date
    numero_factura: str | None = None
    notas: str | None = None

    @model_validator(mode="after")
    def validar_fechas(self):
        if self.fecha_vencimiento < self.fecha_factura:
            raise ValueError("La fecha de vencimiento no puede ser anterior a la factura")
        return self


class PagoCreate(BaseModel):
    monto: Decimal = Field(..., gt=0)
    metodo_pago: str = Field(..., min_length=1, max_length=50)
    referencia: str | None = None
    fecha_pago: date
    notas: str | None = None


class EvaluacionInput(BaseModel):
    periodo_inicio: date
    periodo_fin: date

    @model_validator(mode="after")
    def validar_periodo(self):
        if self.periodo_fin < self.periodo_inicio:
            raise ValueError("El periodo final no puede ser anterior al inicial")
        return self


# --- Proveedores ---

@router.get("/proveedores")
def listar_proveedores(
    solo_activos: bool = Query(True),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "ver")),
):
    """Lista proveedores (cualquier usuario autenticado)."""
    return svc.listar_proveedores(db, solo_activos)


@router.get("/proveedores/{id}")
def obtener_proveedor(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "ver")),
):
    """Detalle de un proveedor con sus ingredientes."""
    try:
        return svc.obtener_proveedor(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Órdenes de compra ---

@router.post("/ordenes", status_code=201)
def crear_orden_compra(
    data: OrdenCompraCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("compras", "editar")),
):
    """Crea una orden de compra con líneas de detalle."""
    try:
        payload = data.model_dump()
        payload["usuario_id"] = user.id
        payload["items"] = [item.model_dump() for item in data.items]
        return svc.crear_orden_compra(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ordenes")
def listar_ordenes_compra(
    estado: str | None = Query(None),
    proveedor_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "ver")),
):
    """Lista órdenes de compra con filtros opcionales."""
    try:
        return svc.listar_ordenes_compra(db, estado, proveedor_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ordenes/{id}")
def obtener_orden_compra(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "ver")),
):
    """Detalle de una orden de compra."""
    try:
        return svc.obtener_orden_compra(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/ordenes/{id}/recibir")
def recibir_orden(
    id: int,
    data: RecepcionOrden,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("compras", "editar")),
):
    """Recibe mercancía: actualiza stock de ingredientes y estado de la orden."""
    try:
        items = [item.model_dump() for item in data.items]
        return svc.recibir_orden(db, id, items, data.idempotency_key, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Cuentas por pagar ---

@router.get("/cuentas-pagar")
def listar_cuentas_pagar(
    estado: str | None = Query(None),
    proveedor_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "ver")),
):
    """Lista cuentas por pagar con filtros."""
    try:
        return svc.listar_cuentas_pagar(db, estado, proveedor_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cuentas-pagar", status_code=201)
def crear_cuenta_pagar(
    data: CuentaPagarCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "editar")),
):
    """Crea una cuenta por pagar."""
    try:
        return svc.crear_cuenta_pagar(db, data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cuentas-pagar/{id}/pago", status_code=201)
def registrar_pago(
    id: int,
    data: PagoCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "editar")),
):
    """Registra un pago a una cuenta por pagar."""
    try:
        return svc.registrar_pago(db, id, data.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Calendario de pagos ---

@router.get("/calendario-pagos")
def calendario_pagos(
    dias: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "ver")),
):
    """Cuentas por pagar que vencen en los próximos N días."""
    return svc.calendario_pagos(db, dias)


# --- Evaluación de proveedores ---

@router.post("/proveedores/{id}/evaluar")
def evaluar_proveedor(
    id: int,
    data: EvaluacionInput,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "editar")),
):
    """Evalúa automáticamente un proveedor en base a órdenes del periodo."""
    try:
        return svc.evaluar_proveedor(db, id, data.periodo_inicio, data.periodo_fin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Dashboard ---

@router.get("/dashboard")
def dashboard_compras(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("compras", "ver")),
):
    """Dashboard resumen del módulo de compras."""
    return svc.dashboard_compras(db)
