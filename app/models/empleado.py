"""
Modelo de empleados.
Cumple con Ley Federal del Trabajo (LFT), IMSS, ISR nómina.
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


class TipoContrato(str, enum.Enum):
    INDETERMINADO = "indeterminado"
    DETERMINADO = "determinado"
    CAPACITACION = "capacitacion"
    PERIODO_PRUEBA = "periodo_prueba"  # Máx 30 días (LFT Art. 39-A)


class TipoJornada(str, enum.Enum):
    DIURNA = "diurna"          # Máx 8 hrs (LFT Art. 60)
    NOCTURNA = "nocturna"      # Máx 7 hrs (LFT Art. 61)
    MIXTA = "mixta"            # Máx 7.5 hrs (LFT Art. 60)


class Departamento(str, enum.Enum):
    PRODUCCION = "produccion"
    VENTAS = "ventas"
    ADMINISTRACION = "administracion"
    LIMPIEZA = "limpieza"


class Empleado(Base):
    __tablename__ = "empleados"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Datos personales
    nombre: Mapped[str] = mapped_column(String(100))
    apellido_paterno: Mapped[str] = mapped_column(String(100))
    apellido_materno: Mapped[str | None] = mapped_column(String(100))
    curp: Mapped[str] = mapped_column(String(18), unique=True)
    rfc: Mapped[str] = mapped_column(String(13), unique=True)
    nss: Mapped[str] = mapped_column(String(11), unique=True)  # Número de Seguro Social
    fecha_nacimiento: Mapped[date] = mapped_column(Date)
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    direccion: Mapped[str | None] = mapped_column(Text)

    # Datos laborales
    numero_empleado: Mapped[str] = mapped_column(String(20), unique=True)
    fecha_ingreso: Mapped[date] = mapped_column(Date)
    fecha_baja: Mapped[date | None] = mapped_column(Date)
    tipo_contrato: Mapped[TipoContrato] = mapped_column(
        SAEnum(TipoContrato), default=TipoContrato.INDETERMINADO
    )
    tipo_jornada: Mapped[TipoJornada] = mapped_column(
        SAEnum(TipoJornada), default=TipoJornada.DIURNA
    )
    departamento: Mapped[Departamento] = mapped_column(
        SAEnum(Departamento), default=Departamento.PRODUCCION
    )
    puesto: Mapped[str] = mapped_column(String(100))

    # Salario y prestaciones
    salario_diario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    salario_diario_integrado: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0")
    )

    # IMSS
    tipo_salario_imss: Mapped[str] = mapped_column(
        String(5), default="02"  # 01=Fijo, 02=Variable, 03=Mixto
    )

    # Vacaciones según LFT (Art. 76, reforma 2023)
    dias_vacaciones_pendientes: Mapped[int] = mapped_column(Integer, default=0)

    # COFEPRIS - Salud del trabajador
    tiene_tarjeta_salud: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_ultima_revision_medica: Mapped[date | None] = mapped_column(Date)
    capacitacion_higiene: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_capacitacion_higiene: Mapped[date | None] = mapped_column(Date)

    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    registros_nomina: Mapped[list["RegistroNomina"]] = relationship(back_populates="empleado")
    registros_asistencia: Mapped[list["RegistroAsistencia"]] = relationship(
        back_populates="empleado"
    )


class RegistroNomina(Base):
    """Registro de nómina quincenal/semanal con desglose ISR e IMSS."""
    __tablename__ = "registros_nomina"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    empleado_id: Mapped[int] = mapped_column(ForeignKey("empleados.id"))
    periodo_inicio: Mapped[date] = mapped_column(Date)
    periodo_fin: Mapped[date] = mapped_column(Date)

    # Percepciones
    salario_base: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    horas_extra_dobles: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    horas_extra_triples: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    monto_horas_extra: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    premio_puntualidad: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    premio_asistencia: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    bono_productividad: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    aguinaldo: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    prima_vacacional: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    ptu: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_percepciones: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    # Deducciones
    isr_retenido: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    imss_trabajador: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    infonavit: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    fonacot: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    otras_deducciones: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    total_deducciones: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    # Cuotas patronales (para cálculo de costo real)
    imss_patron: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    infonavit_patron: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    impuesto_nomina_estatal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0")
    )

    neto_a_pagar: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    pagado: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_pago: Mapped[date | None] = mapped_column(Date)

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    empleado: Mapped["Empleado"] = relationship(back_populates="registros_nomina")


class RegistroAsistencia(Base):
    """Control de asistencia para horas extra LFT."""
    __tablename__ = "registros_asistencia"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    empleado_id: Mapped[int] = mapped_column(ForeignKey("empleados.id"))
    fecha: Mapped[date] = mapped_column(Date)
    hora_entrada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hora_salida: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    horas_trabajadas: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    horas_extra: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    es_dia_festivo: Mapped[bool] = mapped_column(Boolean, default=False)
    es_dia_descanso: Mapped[bool] = mapped_column(Boolean, default=False)
    notas: Mapped[str | None] = mapped_column(String(200))

    empleado: Mapped["Empleado"] = relationship(back_populates="registros_asistencia")
