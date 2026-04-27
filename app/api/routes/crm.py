"""Rutas del módulo CRM y Marketing."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.models.crm import SegmentoCliente
from app.services import crm_service
from app.services import excel_service

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


class CampanaCreate(BaseModel):
    nombre: str = Field(..., max_length=200)
    descripcion: str | None = None
    tipo: str = Field(..., pattern="^(email|whatsapp|push|sms)$")
    segmento_objetivo: SegmentoCliente | None = None
    mensaje: str
    fecha_inicio: date
    fecha_fin: date | None = None
    usuario_id: int | None = None


class EncuestaCreate(BaseModel):
    cliente_id: int
    venta_id: int | None = None
    calificacion: int = Field(..., ge=1, le=5)
    comentario: str | None = None
    categoria: str = Field(..., pattern="^(producto|servicio|ambiente|precio|general)$")


class InteraccionCreate(BaseModel):
    cliente_id: int
    tipo: str = Field(..., pattern="^(compra|queja|consulta|felicitacion|seguimiento)$")
    canal: str = Field(..., pattern="^(presencial|whatsapp|telefono|email)$")
    descripcion: str
    resultado: str | None = None
    usuario_id: int | None = None


# ── Segmentación ────────────────────────────────────────────────────


@router.get("/segmentacion")
def obtener_segmentacion(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Resumen de segmentación de clientes por RFM."""
    return crm_service.obtener_segmentacion(db)


@router.get("/segmentacion/detalle")
def segmentacion_detalle(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Lista completa de clientes con su segmento RFM."""
    return crm_service.segmentar_clientes(db)


@router.get("/clientes-en-riesgo")
def clientes_en_riesgo(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Clientes en riesgo de abandono (última compra >30 días)."""
    return crm_service.clientes_en_riesgo(db)


# ── Campañas ────────────────────────────────────────────────────────


@router.post("/campanas", status_code=201)
def crear_campana(
    data: CampanaCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "editar")),
):
    """Crea una nueva campaña de marketing (ADMIN/GERENTE)."""
    payload = data.model_dump()
    if payload.get("segmento_objetivo"):
        payload["segmento_objetivo"] = payload["segmento_objetivo"].value
    resultado = crm_service.crear_campana(db, payload)
    db.commit()
    return resultado


@router.get("/campanas")
def listar_campanas(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Lista todas las campañas."""
    return crm_service.listar_campanas(db)


@router.post("/campanas/{campana_id}/ejecutar")
def ejecutar_campana(
    campana_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "editar")),
):
    """Ejecuta (simula envío) de una campaña (ADMIN/GERENTE)."""
    try:
        resultado = crm_service.ejecutar_campana(db, campana_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return resultado


# ── Encuestas de Satisfacción ──────────────────────────────────────


@router.post("/encuestas", status_code=201)
def registrar_encuesta(
    data: EncuestaCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "editar")),
):
    """Registra una encuesta de satisfacción (cualquier usuario autenticado)."""
    resultado = crm_service.registrar_encuesta(db, data.model_dump())
    db.commit()
    return resultado


@router.get("/encuestas/resumen")
def resumen_satisfaccion(
    dias: int = Query(default=30, ge=1, le=365, description="Días hacia atrás"),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Resumen de satisfacción de clientes."""
    return crm_service.resumen_satisfaccion(db, dias=dias)


# ── Interacciones ──────────────────────────────────────────────────


@router.post("/interacciones", status_code=201)
def registrar_interaccion(
    data: InteraccionCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "editar")),
):
    """Registra una interacción con un cliente (cualquier usuario autenticado)."""
    resultado = crm_service.registrar_interaccion(db, data.model_dump())
    db.commit()
    return resultado


@router.get("/interacciones/{cliente_id}")
def listar_interacciones(
    cliente_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Lista interacciones de un cliente."""
    return crm_service.listar_interacciones(db, cliente_id)


# ── Predicción de Churn ────────────────────────────────────────────


@router.get("/prediccion-churn")
def prediccion_churn(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Predicción de clientes con probabilidad de abandono (ADMIN/GERENTE)."""
    return crm_service.prediccion_churn(db)


# ── Dashboard ──────────────────────────────────────────────────────


@router.get("/dashboard")
def dashboard_crm(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Dashboard resumen del módulo CRM (ADMIN/GERENTE)."""
    return crm_service.dashboard_crm(db)


# ─── Exportaciones ──────────────────────────────────────────────


@router.get("/exportar-excel")
def exportar_excel(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("crm", "ver")),
):
    """Descarga reporte CRM (segmentación, campañas, satisfacción) en Excel."""
    buf = excel_service.exportar_crm(db)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=crm_reporte.xlsx"},
    )
