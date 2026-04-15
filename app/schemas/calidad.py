"""Schemas de control de calidad y trazabilidad."""

from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import date, datetime


# --- Checklists de calidad ---

class ChecklistCalidadCreate(BaseModel):
    orden_produccion_id: int
    producto_id: int
    fecha_inspeccion: date
    inspector_id: int
    estado: str = "pendiente"
    apariencia: int | None = Field(default=None, ge=1, le=5)
    textura: int | None = Field(default=None, ge=1, le=5)
    sabor: int | None = Field(default=None, ge=1, le=5)
    peso_correcto: bool = False
    empaque_correcto: bool = False
    temperatura_correcta: bool = False
    peso_muestra: Decimal | None = None
    temperatura_muestra: Decimal | None = None
    observaciones: str | None = None
    foto_url: str | None = None


class ChecklistCalidadResponse(BaseModel):
    id: int
    orden_produccion_id: int
    producto_id: int
    fecha_inspeccion: date
    inspector_id: int
    estado: str
    apariencia: int | None
    textura: int | None
    sabor: int | None
    peso_correcto: bool
    empaque_correcto: bool
    temperatura_correcta: bool
    peso_muestra: Decimal | None
    temperatura_muestra: Decimal | None
    observaciones: str | None
    foto_url: str | None
    calificacion_global: Decimal | None
    creado_en: datetime

    model_config = {"from_attributes": True}


# --- Trazabilidad ---

class TrazabilidadLoteCreate(BaseModel):
    lote_ingrediente_id: int
    orden_produccion_id: int | None = None
    producto_id: int | None = None
    cantidad_usada: Decimal = Field(..., gt=0)
    notas: str | None = None


class TrazabilidadLoteResponse(BaseModel):
    id: int
    lote_ingrediente_id: int
    orden_produccion_id: int | None
    producto_id: int | None
    cantidad_usada: Decimal
    fecha_uso: datetime
    notas: str | None

    model_config = {"from_attributes": True}


# --- Alertas de recall ---

class AlertaRecallCreate(BaseModel):
    lote_ingrediente_id: int
    motivo: str
    severidad: str = Field(..., pattern=r"^(baja|media|alta|critica)$")


class AlertaRecallResponse(BaseModel):
    id: int
    lote_ingrediente_id: int
    motivo: str
    severidad: str
    productos_afectados: str
    acciones_tomadas: str | None
    estado: str
    reportado_por: int
    creado_en: datetime
    resuelto_en: datetime | None

    model_config = {"from_attributes": True}


class ResolverRecallRequest(BaseModel):
    acciones_tomadas: str
