"""Rutas de delivery tracking."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.usuario import Usuario
from app.services import delivery_service

router = APIRouter()


class EnRutaRequest(BaseModel):
    repartidor_nombre: str
    repartidor_telefono: str | None = None


@router.post("/{pedido_id}/en-ruta")
def marcar_en_ruta(
    pedido_id: int,
    data: EnRutaRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        pedido = delivery_service.marcar_en_ruta(
            db, pedido_id, data.repartidor_nombre, data.repartidor_telefono
        )
        return {"ok": True, "pedido_id": pedido.id, "estado": pedido.estado.value}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{pedido_id}/entregado")
def marcar_entregado(
    pedido_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        pedido = delivery_service.marcar_entregado(db, pedido_id)
        return {"ok": True, "pedido_id": pedido.id, "estado": pedido.estado.value}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/en-ruta")
def listar_en_ruta(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    pedidos = delivery_service.pedidos_en_ruta(db)
    return [
        {
            "id": p.id, "folio": p.folio, "cliente_nombre": p.cliente_nombre,
            "cliente_telefono": p.cliente_telefono,
            "lugar_entrega": p.lugar_entrega, "repartidor_nombre": p.repartidor_nombre,
            "en_ruta_en": p.en_ruta_en,
        }
        for p in pedidos
    ]


@router.get("/tracking/{folio}")
def tracking_publico(folio: str, db: Session = Depends(get_db)):
    """Tracking público - no requiere autenticación."""
    try:
        return delivery_service.tracking_pedido(db, folio)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return delivery_service.dashboard_delivery(db)
