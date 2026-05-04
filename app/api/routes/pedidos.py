"""Rutas de pedidos especiales."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.schemas.pedido import (
    PedidoCreate,
    PedidoEstadoUpdate,
    PedidoPagoUpdate,
    PedidoResponse,
    PedidoUpdate,
)
from app.services import pedido_service

router = APIRouter()


def _status_from_pedido_error(error: ValueError) -> int:
    return 404 if "no encontrado" in str(error).lower() else 400


@router.post("/", response_model=PedidoResponse)
def crear_pedido(
    data: PedidoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "editar")),
):
    try:
        return pedido_service.crear_pedido(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=list[PedidoResponse])
def listar_pedidos(
    fecha: date | None = Query(None),
    estado: str | None = Query(None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "ver")),
):
    return pedido_service.listar_pedidos(db, fecha=fecha, estado=estado, limit=limit)


@router.get("/hoy", response_model=list[PedidoResponse])
def pedidos_de_hoy(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "ver")),
):
    return pedido_service.pedidos_del_dia(db)


@router.get("/{pedido_id}", response_model=PedidoResponse)
def obtener_pedido(
    pedido_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "ver")),
):
    try:
        return pedido_service.obtener_pedido(db, pedido_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{pedido_id}", response_model=PedidoResponse)
def actualizar_pedido(
    pedido_id: int,
    data: PedidoUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "editar")),
):
    try:
        return pedido_service.actualizar_pedido(db, pedido_id, data, user.id)
    except ValueError as e:
        raise HTTPException(status_code=_status_from_pedido_error(e), detail=str(e))


@router.patch("/{pedido_id}/estado", response_model=PedidoResponse)
def cambiar_estado_pedido(
    pedido_id: int,
    data: PedidoEstadoUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "editar")),
):
    try:
        return pedido_service.cambiar_estado_pedido(db, pedido_id, data.estado, user.id)
    except ValueError as e:
        raise HTTPException(status_code=_status_from_pedido_error(e), detail=str(e))


@router.patch("/{pedido_id}/pago", response_model=PedidoResponse)
def marcar_pago_pedido(
    pedido_id: int,
    data: PedidoPagoUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "editar")),
):
    try:
        return pedido_service.marcar_pago_manual(
            db, pedido_id, data.pagado, user.id, data.motivo
        )
    except ValueError as e:
        raise HTTPException(status_code=_status_from_pedido_error(e), detail=str(e))
