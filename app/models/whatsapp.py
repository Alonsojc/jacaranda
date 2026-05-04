"""Modelos de seguridad para webhooks de WhatsApp."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WhatsAppWebhookEvent(Base):
    """Mensajes recibidos para evitar replays/doble procesamiento."""

    __tablename__ = "whatsapp_webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    phone_number_id: Mapped[str | None] = mapped_column(String(80), index=True)
    sender_phone: Mapped[str | None] = mapped_column(String(30), index=True)
    message_type: Mapped[str | None] = mapped_column(String(30))
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str | None] = mapped_column(Text)
    recibido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
