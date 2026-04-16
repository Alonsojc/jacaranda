"""Rutas de pagos online (Conekta)."""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import pagos_service

router = APIRouter()


class CrearOrdenRequest(BaseModel):
    pedido_id: int
    metodo: str = "card"


class ReembolsoRequest(BaseModel):
    pago_id: int
    monto: Decimal | None = None


@router.post("/crear-orden")
def crear_orden(
    data: CrearOrdenRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        return pagos_service.crear_orden_pago(db, data.pedido_id, data.metodo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/verificar/{order_id}")
def verificar_pago(
    order_id: str,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        return pagos_service.verificar_pago(db, order_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/webhook")
def webhook(payload: dict, db: Session = Depends(get_db)):
    """Webhook público para Conekta."""
    return pagos_service.webhook_conekta(db, payload)


@router.get("/historial")
def historial(
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return pagos_service.historial_pagos(db, limit=limit)


@router.post("/reembolso")
def reembolso(
    data: ReembolsoRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    try:
        return pagos_service.reembolso(db, data.pago_id, data.monto)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
