"""Rutas de gestión de merma (desperdicio/pérdida)."""

from datetime import date
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.services import merma_service as svc
from app.services import excel_service

router = APIRouter()


# --- Schemas inline ---

class MermaCreate(BaseModel):
    producto_id: int | None = None
    ingrediente_id: int | None = None
    tipo: str
    cantidad: Decimal
    unidad_medida: str | None = None
    costo_unitario: Decimal = Decimal("0")
    costo_total: Decimal = Decimal("0")
    motivo: str | None = None
    lote_id: int | None = None
    fecha_merma: date | None = None

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, v: str) -> str:
        tipos_validos = {"caducidad", "produccion", "dano", "devolucion", "otro"}
        if v not in tipos_validos:
            raise ValueError(f"Tipo inválido. Valores permitidos: {', '.join(tipos_validos)}")
        return v


# --- Endpoints ---

@router.post("/", status_code=201)
def registrar_merma(
    data: MermaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("merma", "editar")),
):
    """Registrar merma de producto o ingrediente."""
    try:
        payload = data.model_dump()
        payload["responsable_id"] = user.id
        return svc.registrar_merma(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/")
def listar_mermas(
    fecha_inicio: date | None = Query(None),
    fecha_fin: date | None = Query(None),
    tipo: str | None = Query(None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("merma", "ver")),
):
    """Listar registros de merma con filtros opcionales."""
    try:
        return svc.listar_mermas(db, fecha_inicio, fecha_fin, tipo, skip=skip, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/resumen")
def resumen_merma(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("merma", "ver")),
):
    """Resumen de merma por periodo: totales, por tipo, top productos."""
    return svc.resumen_merma(db, fecha_inicio, fecha_fin)


@router.get("/alertas-caducidad")
def alertas_caducidad(
    dias: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("merma", "ver")),
):
    """Ingredientes y lotes que caducan en los próximos N días."""
    return svc.alertas_caducidad(db, dias)


@router.get("/merma-vs-produccion")
def merma_vs_produccion(
    dias: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("merma", "ver")),
):
    """Porcentaje de merma respecto a producción total."""
    return svc.merma_vs_produccion(db, dias)


@router.get("/dashboard")
def dashboard_merma(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("merma", "ver")),
):
    """Dashboard consolidado de merma: hoy, semana, mes y tendencias."""
    return svc.dashboard_merma(db)


# ─── Exportaciones ──────────────────────────────────────────────

@router.get("/exportar-excel")
def exportar_excel(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("merma", "ver")),
):
    """Descarga reporte de merma en Excel."""
    buf = excel_service.exportar_merma(db, fecha_inicio, fecha_fin)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=merma_{fecha_inicio}_{fecha_fin}.xlsx"
        },
    )
