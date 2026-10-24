"""Diagnóstico administrativo; no activa ni modifica tiendas de Uber Eats."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.usuario import RolUsuario
from app.services import uber_eats_service as svc
from app.services import uber_webhook_service as inbox
from app.services import uber_order_service as orders


router = APIRouter()
_admin = Depends(require_role(RolUsuario.ADMINISTRADOR))


class SandboxActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    accion: Literal["aceptar", "rechazar", "cancelar", "listo"]
    motivo: Literal["ITEM_ISSUE", "STORE_CLOSED", "POS_NOT_READY", "SPECIAL_INSTRUCTIONS", "TECHNICAL_FAILURE", "OTHER"] | None = None
    instrucciones_revisadas: StrictBool = False
    detalle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.get("/preparacion", dependencies=[_admin])
def preparacion(db: Session = Depends(get_db)):
    return {"conexion": svc.configuracion(), "catalogo": svc.preparar_catalogo(db)}


@router.post("/probar-conexion", dependencies=[_admin])
def probar_conexion():
    if not svc.configuracion()["puede_probar"]:
        raise HTTPException(status_code=409, detail="Falta configurar el entorno de pruebas de Uber Eats.")
    try:
        return svc.probar_conexion()
    except svc.UberEatsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.post("/sandbox/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """Only HMAC-authenticated sandbox events; acknowledge after durable commit."""
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "Codificacion no permitida.")
    environment = request.headers.getlist("x-environment")
    if environment and (len(environment) != 1 or environment[0].lower() != "sandbox"):
        raise HTTPException(403, "Solo se reciben eventos de Sandbox.")
    signatures = request.headers.getlist("x-uber-signature")
    if len(signatures) != 1:
        raise HTTPException(401, "Firma de Uber no valida.")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > inbox.MAX_BODY_BYTES:
            raise HTTPException(413, "Notificacion demasiado grande.")
        raw.extend(chunk)
    try:
        inbox.receive_event(db, bytes(raw), signatures[0])
    except inbox.WebhookError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "No se pudo guardar la notificacion. Uber puede reintentar.") from None
    return Response(status_code=200)


@router.get("/sandbox/eventos", dependencies=[_admin])
def sandbox_events(
    limit: int = Query(default=30, ge=1, le=100),
    before_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    try:
        events = inbox.list_events(db, limit, before_id)
    except inbox.WebhookError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    return {"entorno": "sandbox", "eventos": events, "aceptacion_automatica": False}


@router.post("/sandbox/eventos/{event_id}/consultar", dependencies=[_admin])
def inspect_sandbox_order(event_id: UUID, db: Session = Depends(get_db)):
    try:
        return orders.inspect_order(db, event_id)
    except inbox.WebhookError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "No se pudo guardar la consulta de pruebas.") from None


@router.post("/sandbox/pedidos/{order_id}/accion", dependencies=[_admin])
def sandbox_order_action(order_id: UUID, data: SandboxActionRequest, db: Session = Depends(get_db)):
    try:
        return orders.submit_action(db, order_id, data.request_key, data.accion, data.motivo,
                                    data.instrucciones_revisadas, data.detalle_sha256)
    except inbox.WebhookError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(503, "Resultado sin confirmar. Revisa el pedido antes de volver a enviarlo.") from None
