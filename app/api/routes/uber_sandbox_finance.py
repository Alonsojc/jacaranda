"""Mounted exclusively by the authenticated standalone TEST runtime."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.services import uber_finance_storage as storage
from app.services import uber_hosted_finance as finance
from app.services import uber_order_service
from app.services.uber_pos_sandbox_service import RehearsalError


def enabled():
    if not settings.UBER_EATS_SANDBOX_FINANCE_ENABLED:
        raise HTTPException(404, "Not found")
    storage.validate_configuration()


router = APIRouter(prefix="/api/v1/uber-eats/sandbox/finanzas", dependencies=[Depends(enabled)])


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    solo_sandbox_confirmado: StrictBool


class FinanceAction(Confirmation):
    accion: Literal["registrar", "actualizar", "conciliar"]
    detalle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: StrictInt = Field(ge=0)
    referencia: str | None = Field(default=None, max_length=100)
    bruto: str | None = Field(default=None, pattern=r"^\d{1,10}\.\d{2}$")
    deducciones: str | None = Field(default=None, pattern=r"^\d{1,10}\.\d{2}$")
    neto: str | None = Field(default=None, pattern=r"^\d{1,10}\.\d{2}$")


class Exercise(Confirmation):
    request_key: UUID


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except RehearsalError as exc:
        raise HTTPException(409, str(exc)) from None
    except uber_order_service.SandboxRequestError:
        raise HTTPException(502, "Uber no confirmo el detalle TEST; no se registraron cobros.") from None


@router.get("")
def summary(public: Session = Depends(get_db), db: Session = Depends(storage.get_db)):
    return call(finance.report, public, db)


@router.post("/pedidos/{order_id}/consultar")
def preview(order_id: UUID, public: Session = Depends(get_db), db: Session = Depends(storage.get_db)):
    return call(finance.inspect_order, public, db, str(order_id))[0]


@router.post("/pedidos/{order_id}/accion")
def action(order_id: UUID, data: FinanceAction, public: Session = Depends(get_db), db: Session = Depends(storage.get_db)):
    return call(finance.perform, public, db, str(order_id), action=data.accion, digest=data.detalle_sha256,
                revision=data.revision, reviewed=data.solo_sandbox_confirmado, reference=data.referencia,
                gross=data.bruto, deductions=data.deducciones, net=data.neto)


@router.get("/ventas/{sale_id}/ticket")
def ticket(sale_id: int, public: Session = Depends(get_db), db: Session = Depends(storage.get_db)):
    return call(finance.ticket, public, db, sale_id)


@router.post("/ensayo")
def exercise(data: Exercise, db: Session = Depends(storage.get_db)):
    return call(finance.exercise, db, data.request_key, data.solo_sandbox_confirmado)
