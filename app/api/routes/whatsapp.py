"""Rutas de integración WhatsApp Business."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.pedido import Pedido
from app.models.usuario import Usuario
from app.services import whatsapp_service as svc

router = APIRouter()


@router.get("/webhook")
def verificar_webhook(
    mode: str = Query(alias="hub.mode", default=""),
    token: str = Query(alias="hub.verify_token", default=""),
    challenge: str = Query(alias="hub.challenge", default=""),
):
    """Webhook verification handshake (Meta/WhatsApp)."""
    result = svc.verificar_webhook(mode, token, challenge)
    if result:
        return PlainTextResponse(result)
    return PlainTextResponse("Forbidden", status_code=403)


@router.post("/webhook")
async def recibir_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Recibe mensajes entrantes de WhatsApp Business API."""
    payload = await request.json()
    return svc.procesar_webhook(payload, db)


@router.get("/catalogo")
def catalogo(
    db: Session = Depends(get_db),
):
    """Catálogo público de productos (no requiere auth)."""
    return svc.generar_catalogo_json(db)


@router.get("/catalogo/texto")
def catalogo_texto(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("ped", "ver")),
):
    """Catálogo en texto formateado para copiar a WhatsApp."""
    return {"texto": svc.generar_catalogo(db)}


@router.post("/recordatorio/{pedido_id}")
def enviar_recordatorio(
    pedido_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("ped", "editar")),
):
    """Envía recordatorio de entrega por WhatsApp (requiere autenticación)."""
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    enviado = svc.enviar_recordatorio_entrega(db, pedido)
    if not enviado:
        raise HTTPException(
            status_code=422,
            detail="No se pudo enviar el recordatorio. Verifica que el pedido tenga teléfono y no esté entregado/cancelado.",
        )
    return {"ok": True, "message": f"Recordatorio enviado para pedido {pedido.folio}"}
