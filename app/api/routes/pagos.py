"""Rutas de pagos online (Conekta)."""

import json
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import require_permission, require_role
from app.models.pago_online import ClipWebhookEvent
from app.models.usuario import Usuario, RolUsuario
from app.models.venta import EstadoVenta, TerminalPago, Venta
from app.services import clip_service, pagos_service, venta_service
from app.services.auditoria_service import registrar_evento

router = APIRouter()


class CrearOrdenRequest(BaseModel):
    pedido_id: int
    metodo: str = "card"


class ReembolsoRequest(BaseModel):
    pago_id: int
    monto: Decimal | None = None


class ClipPinpadRequest(BaseModel):
    venta_id: int
    serial_number_pos: str | None = None


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


@router.post("/clip/pinpad")
def crear_cobro_clip_pinpad(
    data: ClipPinpadRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("pos", "editar")),
):
    """Envía una venta pendiente a la terminal Clip PinPad."""
    venta = db.query(Venta).filter(Venta.id == data.venta_id).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    if venta.estado == EstadoVenta.CANCELADA:
        raise HTTPException(status_code=400, detail="La venta está cancelada")
    if venta.estado == EstadoVenta.COMPLETADA:
        raise HTTPException(status_code=400, detail="La venta ya está pagada")
    if venta.terminal != TerminalPago.CLIP or not venta.pago_integrado:
        raise HTTPException(status_code=400, detail="La venta no está configurada para CLIP integrado")
    if venta.pago_externo_id:
        return {
            "ok": True,
            "idempotent": True,
            "venta_id": venta.id,
            "folio": venta.folio,
            "payment_id": venta.pago_externo_id,
            "estado": venta.pago_externo_estado or "pendiente",
            "respuesta": json.loads(venta.pago_externo_payload or "{}"),
        }

    try:
        respuesta = clip_service.enviar_cobro_pinpad(
            venta.total,
            venta.folio,
            descripcion=f"Venta {venta.folio}",
            serial_number_pos=data.serial_number_pos,
        )
    except clip_service.ClipAPIError as e:
        venta.pago_externo_estado = "error_envio"
        venta.pago_externo_payload = json.dumps({"error": str(e)}, default=str)
        db.commit()
        raise HTTPException(status_code=502, detail=str(e))

    info = clip_service.extraer_pago_webhook_clip(respuesta)
    venta.pago_proveedor = "clip"
    venta.pago_externo_id = info.get("payment_id") or venta.pago_externo_id
    venta.pago_externo_estado = clip_service.estado_operativo_clip(info.get("status"))
    venta.pago_externo_referencia = venta.folio
    venta.pago_externo_payload = json.dumps(respuesta, default=str)
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="crear_intento_pago",
        modulo="pagos",
        entidad="ventas",
        entidad_id=venta.id,
        datos_nuevos={
            "proveedor": "clip",
            "payment_id": venta.pago_externo_id,
            "estado": venta.pago_externo_estado,
            "mock": bool(respuesta.get("mock")),
            "folio": venta.folio,
            "total": str(venta.total),
        },
        commit=False,
    )
    db.commit()
    db.refresh(venta)
    return {
        "ok": True,
        "venta_id": venta.id,
        "folio": venta.folio,
        "payment_id": venta.pago_externo_id,
        "estado": venta.pago_externo_estado,
        "respuesta": respuesta,
    }


@router.get("/clip/pinpad/{venta_id}")
def estado_cobro_clip_pinpad(
    venta_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("pos", "ver")),
):
    venta = db.query(Venta).filter(Venta.id == venta_id).first()
    if not venta:
        raise HTTPException(status_code=404, detail="Venta no encontrada")
    if (
        venta.pago_integrado
        and venta.pago_proveedor == "clip"
        and venta.pago_externo_id
        and venta.estado == EstadoVenta.PENDIENTE
    ):
        try:
            respuesta = clip_service.consultar_pago_pinpad(venta.pago_externo_id)
            info = clip_service.extraer_pago_webhook_clip(respuesta)
            if clip_service.es_pago_clip_aprobado(info.get("status")):
                venta_service.finalizar_pago_integrado(
                    db,
                    venta.id,
                    "clip",
                    info.get("payment_id") or venta.pago_externo_id,
                    respuesta,
                )
            elif clip_service.es_pago_clip_fallido(info.get("status")):
                venta_service.marcar_pago_integrado_fallido(
                    db,
                    venta.id,
                    "clip",
                    info.get("payment_id") or venta.pago_externo_id,
                    info.get("status") or "fallido",
                    respuesta,
                )
            elif info.get("status"):
                venta.pago_externo_estado = clip_service.estado_operativo_clip(info.get("status"))
                venta.pago_externo_payload = json.dumps(respuesta, default=str)
                db.commit()
                db.refresh(venta)
        except clip_service.ClipAPIError:
            pass
    return {
        "venta_id": venta.id,
        "folio": venta.folio,
        "estado_venta": venta.estado.value,
        "proveedor": venta.pago_proveedor,
        "payment_id": venta.pago_externo_id,
        "estado_pago": venta.pago_externo_estado,
        "verificado_en": venta.pago_verificado_en,
    }


@router.post("/clip/webhook")
async def webhook_clip(
    request: Request,
    secret: str | None = None,
    db: Session = Depends(get_db),
):
    """Webhook público de Clip PinPad con replay protection."""
    configured_secret = (settings.CLIP_WEBHOOK_SECRET or "").strip()
    header_secret = request.headers.get("x-clip-webhook-secret")
    if configured_secret:
        if secret != configured_secret and header_secret != configured_secret:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Webhook no autorizado")
    elif not settings.CLIP_ALLOW_UNSIGNED_WEBHOOKS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Webhook de CLIP sin secreto configurado",
        )

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido")

    info = clip_service.extraer_pago_webhook_clip(payload)
    event_id = info["event_id"]
    existente = db.query(ClipWebhookEvent).filter(
        ClipWebhookEvent.event_id == event_id
    ).first()
    if existente:
        return {"ok": True, "duplicate": True, "event_id": event_id}

    event = ClipWebhookEvent(
        event_id=event_id,
        event_type=info.get("event_type"),
        payment_id=info.get("payment_id"),
        payload_json=json.dumps(payload, default=str),
    )
    db.add(event)
    db.flush()

    venta = None
    if info.get("reference"):
        venta = db.query(Venta).filter(Venta.folio == info["reference"]).first()
    if not venta and info.get("payment_id"):
        venta = db.query(Venta).filter(Venta.pago_externo_id == info["payment_id"]).first()
    if not venta:
        db.commit()
        return {"ok": True, "processed": False, "reason": "venta_no_encontrada", "event_id": event_id}

    event.venta_id = venta.id
    amount = info.get("amount")
    if amount not in (None, ""):
        try:
            amount_decimal = Decimal(str(amount)).quantize(Decimal("0.01"))
            if amount_decimal != Decimal(str(venta.total)).quantize(Decimal("0.01")):
                db.commit()
                raise HTTPException(status_code=400, detail="Monto de CLIP no coincide con la venta")
        except HTTPException:
            raise
        except Exception:
            pass

    try:
        if clip_service.es_pago_clip_aprobado(info.get("status")):
            venta_service.finalizar_pago_integrado(
                db,
                venta.id,
                "clip",
                info.get("payment_id"),
                payload,
                usuario_id=None,
                commit=False,
            )
            event.processed = True
        elif clip_service.es_pago_clip_fallido(info.get("status")):
            venta_service.marcar_pago_integrado_fallido(
                db,
                venta.id,
                "clip",
                info.get("payment_id"),
                clip_service.estado_operativo_clip(info.get("status")),
                payload,
                commit=False,
            )
            event.processed = True
        else:
            venta.pago_proveedor = "clip"
            venta.pago_externo_id = info.get("payment_id") or venta.pago_externo_id
            venta.pago_externo_estado = clip_service.estado_operativo_clip(info.get("status"))
            venta.pago_externo_payload = json.dumps(payload, default=str)
            event.processed = True
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "processed": event.processed, "event_id": event_id}
