"""Schemas de empleados y nómina."""

from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
from datetime import date, datetime
import re

from app.models.empleado import TipoContrato, TipoJornada, Departamento


class EmpleadoCreate(BaseModel):
    nombre: str = Field(..., max_length=100)
    apellido_paterno: str = Field(..., max_length=100)
    apellido_materno: str | None = None
    curp: str = Field(..., min_length=18, max_length=18)
    rfc: str = Field(..., min_length=12, max_length=13)
    nss: str = Field(..., min_length=11, max_length=11)
    fecha_nacimiento: date
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    numero_empleado: str
    fecha_ingreso: date
    tipo_contrato: TipoContrato = TipoContrato.INDETERMINADO
    tipo_jornada: TipoJornada = TipoJornada.DIURNA
    departamento: Departamento = Departamento.PRODUCCION
    puesto: str
    salario_diario: Decimal

    @field_validator("curp")
    @classmethod
    def validar_curp(cls, v: str) -> str:
        v = v.upper().strip()
        pattern = r"^[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d$"
        if not re.match(pattern, v):
            raise ValueError("CURP con formato inválido")
        return v

    @field_validator("nss")
    @classmethod
    def validar_nss(cls, v: str) -> str:
        if not re.match(r"^\d{11}$", v):
            raise ValueError("NSS debe ser de 11 dígitos")
        return v


class EmpleadoUpdate(BaseModel):
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    puesto: str | None = None
    salario_diario: Decimal | None = None
    activo: bool | None = None
    tiene_tarjeta_salud: bool | None = None
    capacitacion_higiene: bool | None = None


class EmpleadoResponse(BaseModel):
    id: int
    nombre: str
    apellido_paterno: str
    apellido_materno: str | None
    numero_empleado: str
    fecha_ingreso: date
    tipo_contrato: TipoContrato
    tipo_jornada: TipoJornada
    departamento: Departamento
    puesto: str
    salario_diario: Decimal
    salario_diario_integrado: Decimal
    dias_vacaciones_pendientes: int
    tiene_tarjeta_salud: bool
    capacitacion_higiene: bool
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


# --- Asistencia ---

class AsistenciaCreate(BaseModel):
    empleado_id: int
    fecha: date
    hora_entrada: datetime
    hora_salida: datetime | None = None
    es_dia_festivo: bool = False
    es_dia_descanso: bool = False
    notas: str | None = None


class AsistenciaResponse(BaseModel):
    id: int
    empleado_id: int
    fecha: date
    hora_entrada: datetime | None
    hora_salida: datetime | None
    horas_trabajadas: Decimal
    horas_extra: Decimal
    es_dia_festivo: bool
    es_dia_descanso: bool

    model_config = {"from_attributes": True}


# --- Nómina ---

class NominaCalculoRequest(BaseModel):
    empleado_id: int
    periodo_inicio: date
    periodo_fin: date
    incluir_aguinaldo: bool = False
    incluir_prima_vacacional: bool = False
    incluir_ptu: bool = False
    dias_ptu: int | None = None


class NominaResponse(BaseModel):
    id: int
    empleado_id: int
    periodo_inicio: date
    periodo_fin: date
    salario_base: Decimal
    monto_horas_extra: Decimal
    total_percepciones: Decimal
    isr_retenido: Decimal
    imss_trabajador: Decimal
    total_deducciones: Decimal
    neto_a_pagar: Decimal
    pagado: bool

    model_config = {"from_attributes": True}
