"""Schemas de recetas y producción."""

from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime


class RecetaIngredienteSchema(BaseModel):
    ingrediente_id: int
    cantidad: Decimal
    notas: str | None = None


class RecetaCreate(BaseModel):
    producto_id: int
    nombre: str = Field(..., max_length=200)
    descripcion: str | None = None
    instrucciones: str | None = None
    rendimiento: Decimal
    tiempo_preparacion_min: int | None = None
    tiempo_horneado_min: int | None = None
    temperatura_horneado_c: int | None = None
    ingredientes: list[RecetaIngredienteSchema] = []


class RecetaUpdate(BaseModel):
    nombre: str | None = None
    instrucciones: str | None = None
    rendimiento: Decimal | None = None
    activo: bool | None = None


class RecetaIngredienteResponse(BaseModel):
    id: int
    ingrediente_id: int
    cantidad: Decimal
    notas: str | None

    model_config = {"from_attributes": True}


class RecetaResponse(BaseModel):
    id: int
    producto_id: int
    nombre: str
    descripcion: str | None
    rendimiento: Decimal
    tiempo_preparacion_min: int | None
    tiempo_horneado_min: int | None
    temperatura_horneado_c: int | None
    activo: bool
    ingredientes: list[RecetaIngredienteResponse] = []
    creado_en: datetime

    model_config = {"from_attributes": True}


class CostoRecetaResponse(BaseModel):
    receta_id: int
    nombre: str
    rendimiento: Decimal
    costo_total_ingredientes: Decimal
    costo_por_pieza: Decimal
    desglose: list[dict]


# --- Ordenes de producción ---

class OrdenProduccionCreate(BaseModel):
    receta_id: int
    cantidad_lotes: Decimal = Decimal("1")
    fecha_programada: datetime
    responsable_id: int | None = None
    notas: str | None = None


class OrdenProduccionResponse(BaseModel):
    id: int
    receta_id: int
    cantidad_lotes: Decimal
    estado: str
    cantidad_producida: Decimal
    cantidad_merma: Decimal
    fecha_programada: datetime
    fecha_inicio: datetime | None
    fecha_fin: datetime | None
    creado_en: datetime

    model_config = {"from_attributes": True}
