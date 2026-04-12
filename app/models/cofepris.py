"""
Modelos de cumplimiento COFEPRIS y normas sanitarias.
NOM-251-SSA1-2009: Prácticas de higiene para alimentos.
NOM-051-SCFI/SSA1-2010: Etiquetado de alimentos y bebidas.
"""

from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, ForeignKey, Text,
    Numeric, Boolean, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class TipoRegistro(str, enum.Enum):
    TEMPERATURA = "temperatura"
    LIMPIEZA = "limpieza"
    FUMIGACION = "fumigacion"
    CAPACITACION = "capacitacion"
    INSPECCION = "inspeccion"
    MANTENIMIENTO = "mantenimiento"


class EstadoCumplimiento(str, enum.Enum):
    CONFORME = "conforme"
    NO_CONFORME = "no_conforme"
    ACCION_CORRECTIVA = "accion_correctiva"
    PENDIENTE = "pendiente"


class AreaEstablecimiento(str, enum.Enum):
    PRODUCCION = "produccion"
    ALMACEN_SECO = "almacen_seco"
    REFRIGERACION = "refrigeracion"
    CONGELACION = "congelacion"
    PUNTO_VENTA = "punto_venta"
    SANITARIOS = "sanitarios"
    AREA_LAVADO = "area_lavado"


class RegistroTemperatura(Base):
    """
    Control de temperaturas - NOM-251-SSA1-2009.
    Obligatorio para áreas de refrigeración y congelación.
    """
    __tablename__ = "registros_temperatura"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    area: Mapped[AreaEstablecimiento] = mapped_column(SAEnum(AreaEstablecimiento))
    equipo: Mapped[str] = mapped_column(String(100))  # "Refrigerador 1", "Horno 2"
    temperatura_registrada: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    temperatura_minima: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    temperatura_maxima: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    en_rango: Mapped[bool] = mapped_column(Boolean)
    accion_correctiva: Mapped[str | None] = mapped_column(Text)
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("empleados.id"))
    fecha_registro: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RegistroLimpieza(Base):
    """
    Bitácora de limpieza y desinfección - NOM-251-SSA1-2009.
    """
    __tablename__ = "registros_limpieza"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    area: Mapped[AreaEstablecimiento] = mapped_column(SAEnum(AreaEstablecimiento))
    actividad: Mapped[str] = mapped_column(String(200))
    productos_utilizados: Mapped[str | None] = mapped_column(String(300))
    estado: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.CONFORME
    )
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("empleados.id"))
    supervisor_id: Mapped[int | None] = mapped_column(ForeignKey("empleados.id"))
    notas: Mapped[str | None] = mapped_column(Text)
    fecha_registro: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ControlPlagas(Base):
    """Control de plagas y fumigaciones."""
    __tablename__ = "control_plagas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    empresa_fumigadora: Mapped[str] = mapped_column(String(200))
    licencia_sanitaria_empresa: Mapped[str | None] = mapped_column(String(100))
    tipo_servicio: Mapped[str] = mapped_column(String(100))
    productos_aplicados: Mapped[str | None] = mapped_column(Text)
    areas_tratadas: Mapped[str | None] = mapped_column(Text)
    fecha_servicio: Mapped[date] = mapped_column(Date)
    proxima_fecha: Mapped[date | None] = mapped_column(Date)
    certificado_numero: Mapped[str | None] = mapped_column(String(100))
    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class InspeccionSanitaria(Base):
    """Inspecciones internas y de COFEPRIS."""
    __tablename__ = "inspecciones_sanitarias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(50))  # "interna", "cofepris", "cliente"
    inspector: Mapped[str] = mapped_column(String(200))
    fecha_inspeccion: Mapped[date] = mapped_column(Date)

    # Checklist NOM-251
    higiene_personal: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    instalaciones: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    equipos_utensilios: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    control_operaciones: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    control_materias_primas: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    almacenamiento: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    control_temperaturas: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    manejo_residuos: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    control_agua: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    capacitacion_personal: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )
    etiquetado: Mapped[EstadoCumplimiento] = mapped_column(
        SAEnum(EstadoCumplimiento), default=EstadoCumplimiento.PENDIENTE
    )

    calificacion_general: Mapped[int | None] = mapped_column(Integer)  # 0-100
    observaciones: Mapped[str | None] = mapped_column(Text)
    acciones_correctivas: Mapped[str | None] = mapped_column(Text)
    fecha_seguimiento: Mapped[date | None] = mapped_column(Date)

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class LicenciaSanitaria(Base):
    """Licencias y permisos sanitarios del establecimiento."""
    __tablename__ = "licencias_sanitarias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String(100))
    numero_licencia: Mapped[str] = mapped_column(String(100))
    autoridad_emisora: Mapped[str] = mapped_column(String(200))
    fecha_emision: Mapped[date] = mapped_column(Date)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(50), default="vigente")
    documento_path: Mapped[str | None] = mapped_column(String(500))
    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
