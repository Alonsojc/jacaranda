"""Rutas del dashboard ejecutivo."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import ejecutivo_service

router = APIRouter()


def _require_gerencia():
    return require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(_require_gerencia()),
):
    return ejecutivo_service.dashboard_ejecutivo(db)


@router.get("/resumen-semanal")
def resumen_semanal(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(_require_gerencia()),
):
    return ejecutivo_service.resumen_semanal(db)


@router.get("/comparativo")
def comparativo(
    dias: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(_require_gerencia()),
):
    return ejecutivo_service.comparativo_periodos(db, dias=dias)
