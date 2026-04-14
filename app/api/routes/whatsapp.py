"""Rutas de integración WhatsApp Business."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
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
    _user: Usuario = Depends(get_current_user),
):
    """Catálogo en texto formateado para copiar a WhatsApp."""
    return {"texto": svc.generar_catalogo(db)}
