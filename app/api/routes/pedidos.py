"""Rutas de pedidos especiales."""

from datetime import date
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission
from app.models.pedido import Pedido
from app.models.usuario import Usuario
from app.schemas.pedido import (
    PedidoCreate,
    PedidoEstadoUpdate,
    PedidoPagoUpdate,
    PedidoResponse,
    PedidoUpdate,
)
from app.services import pedido_service
from app.services.notificacion_service import notificar_pedido_nuevo

router = APIRouter()


def _status_from_pedido_error(error: ValueError) -> int:
    return 404 if "no encontrado" in str(error).lower() else 400


def _payload_notificacion_pedido(pedido: Pedido) -> dict:
    return {
        "pedido_id": pedido.id,
        "folio": pedido.folio,
        "cliente": pedido.cliente_nombre,
        "fecha_entrega": pedido.fecha_entrega.isoformat() if pedido.fecha_entrega else None,
        "total": str(pedido.total) if pedido.total is not None else None,
        "origen": pedido.origen.value if pedido.origen else None,
    }


@router.post("/", response_model=PedidoResponse)
def crear_pedido(
    data: PedidoCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "editar")),
):
    try:
        pedido_preexistente = None
        if data.idempotency_key:
            pedido_preexistente = db.query(Pedido).filter(
                Pedido.idempotency_key == data.idempotency_key
            ).first()
        pedido = pedido_service.crear_pedido(db, data)
        if not pedido_preexistente:
            background_tasks.add_task(
                notificar_pedido_nuevo,
                _payload_notificacion_pedido(pedido),
            )
        return pedido
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


@router.get("/reservas")
def reservas_pedidos(
    fecha: date | None = Query(None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("ped", "ver")),
):
    return pedido_service.resumen_reservas(db, fecha)


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


@router.delete("/{pedido_id}", response_model=PedidoResponse)
def borrar_pedido(
    pedido_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("ped", "borrar pedido")),
    motivo: str | None = Header(default=None, alias="X-Admin-Override-Motivo"),
):
    """Anula un pedido de forma auditada; no elimina el histórico de la base."""
    try:
        return pedido_service.cancelar_pedido(
            db,
            pedido_id,
            usuario_id=user.id,
            motivo=unquote(motivo or "").strip() or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=_status_from_pedido_error(e), detail=str(e))
