"""Rutas de pagos online (Conekta)."""

import json
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission, require_role
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
    user: Usuario = Depends(require_permission("pos", "editar")),
):
    try:
        return pagos_service.crear_orden_pago(db, data.pedido_id, data.metodo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/verificar/{order_id}")
def verificar_pago(
    order_id: str,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("pos", "ver")),
):
    try:
        return pagos_service.verificar_pago(db, order_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Webhook público para Conekta."""
    raw_body = await request.body()
    try:
        pagos_service.verificar_firma_webhook_conekta(
            raw_body,
            request.headers.get("digest"),
        )
        payload = json.loads(raw_body)
    except pagos_service.WebhookSignatureError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido")
    return pagos_service.webhook_conekta(db, payload)


@router.get("/historial")
def historial(
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("corte", "ver")),
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
