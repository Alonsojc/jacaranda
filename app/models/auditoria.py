"""Modelos de auditoría y configuración de seguridad."""

from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LogAuditoria(Base):
    """Registro de eventos de auditoría del sistema."""
    __tablename__ = "log_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    usuario_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("usuarios.id"), index=True
    )
    usuario_nombre: Mapped[str | None] = mapped_column(String(200))
    accion: Mapped[str] = mapped_column(String(50))  # crear, actualizar, eliminar, login, logout, consultar
    modulo: Mapped[str] = mapped_column(String(100))  # inventario, ventas, empleados, etc.
    entidad: Mapped[str | None] = mapped_column(String(100))  # Tabla/modelo afectado
    entidad_id: Mapped[int | None] = mapped_column(Integer)
    datos_anteriores: Mapped[str | None] = mapped_column(Text)  # JSON valores anteriores
    datos_nuevos: Mapped[str | None] = mapped_column(Text)  # JSON valores nuevos
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


class ConfiguracionSeguridad(Base):
    """Parámetros de configuración de seguridad del sistema."""
    __tablename__ = "configuracion_seguridad"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    clave: Mapped[str] = mapped_column(String(100), unique=True)
    valor: Mapped[str] = mapped_column(Text)
    descripcion: Mapped[str | None] = mapped_column(Text)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
