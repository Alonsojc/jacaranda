"""Rutas de gestión de proveedores y compras."""

from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import compras_service as svc

router = APIRouter()


# --- Schemas ---

class ItemOrdenCompra(BaseModel):
    ingrediente_id: int
    cantidad: Decimal
    precio_unitario: Decimal
    notas: str | None = None


class OrdenCompraCreate(BaseModel):
    proveedor_id: int
    sucursal_id: int | None = None
    fecha_entrega_esperada: date | None = None
    notas: str | None = None
    items: list[ItemOrdenCompra]


class ItemRecibido(BaseModel):
    detalle_id: int
    cantidad_recibida: Decimal


class RecepcionOrden(BaseModel):
    items: list[ItemRecibido]


class CuentaPagarCreate(BaseModel):
    proveedor_id: int
    orden_compra_id: int | None = None
    concepto: str
    monto_total: Decimal
    fecha_factura: date
    fecha_vencimiento: date
    numero_factura: str | None = None
    notas: str | None = None


class PagoCreate(BaseModel):
    monto: Decimal
    metodo_pago: str
    referencia: str | None = None
    fecha_pago: date
    notas: str | None = None


class EvaluacionInput(BaseModel):
    periodo_inicio: date
    periodo_fin: date


# --- Proveedores ---

@router.get("/proveedores")
def listar_proveedores(
    solo_activos: bool = Query(True),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Lista proveedores (cualquier usuario autenticado)."""
    return svc.listar_proveedores(db, solo_activos)


@router.get("/proveedores/{id}")
def obtener_proveedor(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
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
    user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE
    )),
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
    _user: Usuario = Depends(get_current_user),
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
    _user: Usuario = Depends(get_current_user),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE, RolUsuario.ALMACENISTA
    )),
):
    """Recibe mercancía: actualiza stock de ingredientes y estado de la orden."""
    try:
        items = [item.model_dump() for item in data.items]
        return svc.recibir_orden(db, id, items)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Cuentas por pagar ---

@router.get("/cuentas-pagar")
def listar_cuentas_pagar(
    estado: str | None = Query(None),
    proveedor_id: int | None = Query(None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR, RolUsuario.GERENTE
    )),
):
    """Cuentas por pagar que vencen en los próximos N días."""
    return svc.calendario_pagos(db, dias)


# --- Evaluación de proveedores ---

@router.post("/proveedores/{id}/evaluar")
def evaluar_proveedor(
    id: int,
    data: EvaluacionInput,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE
    )),
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
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE, RolUsuario.CONTADOR
    )),
):
    """Dashboard resumen del módulo de compras."""
    return svc.dashboard_compras(db)
