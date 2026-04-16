"""Modelo de pagos online (Conekta)."""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    String, DateTime, ForeignKey, Text, Numeric, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class EstadoPago(str, enum.Enum):
    PENDIENTE = "pendiente"
    PAGADO = "pagado"
    FALLIDO = "fallido"
    REEMBOLSADO = "reembolsado"


class PagoOnline(Base):
    __tablename__ = "pagos_online"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    order_id_externo: Mapped[str] = mapped_column(String(100), unique=True)
    metodo: Mapped[str] = mapped_column(String(20))  # card, oxxo, spei
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    moneda: Mapped[str] = mapped_column(String(3), default="MXN")
    estado: Mapped[EstadoPago] = mapped_column(
        SAEnum(EstadoPago), default=EstadoPago.PENDIENTE
    )
    checkout_url: Mapped[str | None] = mapped_column(String(500))
    referencia: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    pedido: Mapped["Pedido"] = relationship()  # noqa: F821
