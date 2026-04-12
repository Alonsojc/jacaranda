"""Schemas de cumplimiento COFEPRIS."""

from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import date, datetime

from app.models.cofepris import AreaEstablecimiento, EstadoCumplimiento


# --- Temperatura ---

class TemperaturaCreate(BaseModel):
    area: AreaEstablecimiento
    equipo: str = Field(..., max_length=100)
    temperatura_registrada: Decimal
    responsable_id: int | None = None
    accion_correctiva: str | None = None


class TemperaturaResponse(BaseModel):
    id: int
    area: AreaEstablecimiento
    equipo: str
    temperatura_registrada: Decimal
    temperatura_minima: Decimal
    temperatura_maxima: Decimal
    en_rango: bool
    accion_correctiva: str | None
    fecha_registro: datetime

    model_config = {"from_attributes": True}


# --- Limpieza ---

class LimpiezaCreate(BaseModel):
    area: AreaEstablecimiento
    actividad: str
    productos_utilizados: str | None = None
    responsable_id: int | None = None
    supervisor_id: int | None = None
    notas: str | None = None


class LimpiezaResponse(BaseModel):
    id: int
    area: AreaEstablecimiento
    actividad: str
    estado: EstadoCumplimiento
    fecha_registro: datetime

    model_config = {"from_attributes": True}


# --- Inspección sanitaria ---

class InspeccionCreate(BaseModel):
    tipo: str
    inspector: str
    fecha_inspeccion: date
    higiene_personal: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    instalaciones: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    equipos_utensilios: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    control_operaciones: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    control_materias_primas: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    almacenamiento: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    control_temperaturas: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    manejo_residuos: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    control_agua: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    capacitacion_personal: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    etiquetado: EstadoCumplimiento = EstadoCumplimiento.PENDIENTE
    calificacion_general: int | None = None
    observaciones: str | None = None
    acciones_correctivas: str | None = None


class InspeccionResponse(BaseModel):
    id: int
    tipo: str
    inspector: str
    fecha_inspeccion: date
    calificacion_general: int | None
    observaciones: str | None
    creado_en: datetime

    model_config = {"from_attributes": True}


# --- Control de plagas ---

class ControlPlagasCreate(BaseModel):
    empresa_fumigadora: str
    licencia_sanitaria_empresa: str | None = None
    tipo_servicio: str
    productos_aplicados: str | None = None
    areas_tratadas: str | None = None
    fecha_servicio: date
    proxima_fecha: date | None = None
    certificado_numero: str | None = None
    notas: str | None = None


class ControlPlagasResponse(BaseModel):
    id: int
    empresa_fumigadora: str
    tipo_servicio: str
    fecha_servicio: date
    proxima_fecha: date | None
    certificado_numero: str | None
    creado_en: datetime

    model_config = {"from_attributes": True}


# --- Etiquetado NOM-051 ---

class EtiquetadoNOM051Response(BaseModel):
    producto_id: int
    nombre_producto: str
    peso_neto_g: Decimal | None
    informacion_nutrimental: dict
    sellos_advertencia: list[str]
    leyendas_precautorias: list[str]
