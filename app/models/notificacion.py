"""Modelos para notificaciones push."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FCMToken(Base):
    """Token de Firebase Cloud Messaging asociado a un navegador/dispositivo."""

    __tablename__ = "fcm_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(Integer, ForeignKey("usuarios.id"), index=True)
    token: Mapped[str] = mapped_column(Text, unique=True)
    plataforma: Mapped[str | None] = mapped_column(String(80))
    user_agent: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    ultimo_error: Mapped[str | None] = mapped_column(Text)
    registrado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    ultimo_envio_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
