"""Rutas de IA: pronóstico de demanda y pricing dinámico."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.services import ia_service as svc

router = APIRouter()


@router.get("/dashboard")
def dashboard_ia(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("iapg", "ver")),
):
    """Dashboard consolidado de IA."""
    return svc.dashboard_ia(db)


@router.get("/pronostico-demanda")
def pronostico_demanda(
    dias: int = Query(default=7, le=14),
    semanas: int = Query(default=8, le=12),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("iapg", "ver")),
):
    """Pronóstico de demanda por producto para los próximos N días."""
    return svc.pronostico_demanda(db, dias_futuro=dias, semanas_historico=semanas)


@router.get("/produccion-sugerida")
def produccion_sugerida(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("iapg", "ver")),
):
    """Sugerencia de producción para mañana basada en IA."""
    return svc.pronostico_produccion_ia(db)


@router.get("/pricing")
def analisis_pricing(
    dias: int = Query(default=60, le=90),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("iapg", "ver")),
):
    """Análisis de pricing: elasticidad, sugerencias, rotación."""
    return svc.analisis_pricing(db, dias)


@router.get("/precision")
def precision_modelo(
    dias: int = Query(default=14, le=30),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("iapg", "ver")),
):
    """Precisión del modelo de pronóstico."""
    return svc.precision_modelo(db, dias_atras=dias)
