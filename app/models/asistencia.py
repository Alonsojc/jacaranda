"""Clock evidence and staff schedules, separate from payroll attendance."""

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChecadaAsistencia(Base):
    __tablename__ = "asistencia_checadas"
    __table_args__ = (Index("ix_asistencia_cuenta_fecha", "cuenta", "fecha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    identidad: Mapped[str] = mapped_column(String(64), unique=True)
    cuenta: Mapped[str] = mapped_column(String(140))
    numero_reloj: Mapped[str] = mapped_column(String(80))
    nombre_reloj: Mapped[str] = mapped_column(String(201))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tipo_original: Mapped[int] = mapped_column(Integer)
    dispositivo: Mapped[str] = mapped_column(String(80))
    dispositivo_nombre: Mapped[str] = mapped_column(String(100))
    importado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class VinculoAsistencia(Base):
    __tablename__ = "asistencia_vinculos"
    __table_args__ = (
        UniqueConstraint("cuenta", "numero_reloj", name="uq_asistencia_reloj"),
        UniqueConstraint("cuenta", "empleado_id", name="uq_asistencia_empleado"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta: Mapped[str] = mapped_column(String(140))
    numero_reloj: Mapped[str] = mapped_column(String(80))
    empleado_id: Mapped[int] = mapped_column(ForeignKey("empleados.id"))
    creado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SincronizacionAsistencia(Base):
    __tablename__ = "asistencia_sincronizaciones"
    __table_args__ = (Index("ix_asistencia_sync_cuenta", "cuenta", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta: Mapped[str] = mapped_column(String(140))
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    nuevas: Mapped[int] = mapped_column(Integer)
    repetidas: Mapped[int] = mapped_column(Integer)
    omitidas_otro_equipo: Mapped[int] = mapped_column(Integer)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    completada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PersonaHorarioAsistencia(Base):
    """Display identity used for scheduling, including staff without a payroll profile."""

    __tablename__ = "asistencia_personas_horario"
    __table_args__ = (UniqueConstraint("cuenta_reloj", "numero_reloj", name="uq_asistencia_horario_reloj"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(100))
    nombre_normalizado: Mapped[str] = mapped_column(String(300), unique=True)
    cuenta_reloj: Mapped[str | None] = mapped_column(String(140))
    numero_reloj: Mapped[str | None] = mapped_column(String(80))


class HorarioSemanalAsistencia(Base):
    __tablename__ = "asistencia_horarios_semanales"

    persona_id: Mapped[int] = mapped_column(ForeignKey("asistencia_personas_horario.id"), primary_key=True)
    vigente_desde: Mapped[date] = mapped_column(Date, primary_key=True)
    dias: Mapped[dict] = mapped_column(JSON)
    modalidad: Mapped[str] = mapped_column(String(20))
    nota: Mapped[str] = mapped_column(String(300))


class TurnoFechaAsistencia(Base):
    __tablename__ = "asistencia_turnos_fecha"
    __table_args__ = (Index("ix_asistencia_turnos_fecha", "fecha"),)

    persona_id: Mapped[int] = mapped_column(ForeignKey("asistencia_personas_horario.id"), primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20))
    horas: Mapped[dict | None] = mapped_column(JSON(none_as_null=True))
    modalidad: Mapped[str] = mapped_column(String(20))
    nota: Mapped[str] = mapped_column(String(300))
