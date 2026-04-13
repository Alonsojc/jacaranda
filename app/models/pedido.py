"""Modelo de pedidos especiales (pasteles, eventos, entregas)."""

from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, ForeignKey, Text,
    Numeric, Boolean, Enum as SAEnum, Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class EstadoPedido(str, enum.Enum):
    RECIBIDO = "recibido"
    CONFIRMADO = "confirmado"
    EN_PREPARACION = "en_preparacion"
    LISTO = "listo"
    ENTREGADO = "entregado"
    CANCELADO = "cancelado"


class OrigenPedido(str, enum.Enum):
    WHATSAPP = "whatsapp"
    TIENDA = "tienda"
    TELEFONO = "telefono"
    INSTAGRAM = "instagram"


class Pedido(Base):
    """Pedido especial (pasteles personalizados, eventos, entregas)."""
    __tablename__ = "pedidos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folio: Mapped[str] = mapped_column(String(20), unique=True, index=True)

    # Cliente
    cliente_nombre: Mapped[str] = mapped_column(String(200))
    cliente_telefono: Mapped[str | None] = mapped_column(String(20))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))

    # Entrega
    fecha_entrega: Mapped[date] = mapped_column(Date)
    hora_entrega: Mapped[str | None] = mapped_column(String(10))  # "14:00"
    lugar_entrega: Mapped[str | None] = mapped_column(String(300))

    # Estado y origen
    estado: Mapped[EstadoPedido] = mapped_column(
        SAEnum(EstadoPedido), default=EstadoPedido.RECIBIDO
    )
    origen: Mapped[OrigenPedido] = mapped_column(
        SAEnum(OrigenPedido), default=OrigenPedido.WHATSAPP
    )

    # Totales
    anticipo: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    pagado: Mapped[bool] = mapped_column(Boolean, default=False)

    notas: Mapped[str | None] = mapped_column(Text)
    notas_internas: Mapped[str | None] = mapped_column(Text)  # Solo para staff

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relaciones
    detalles: Mapped[list["DetallePedido"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan"
    )


class DetallePedido(Base):
    __tablename__ = "detalles_pedido"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"))
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id"))

    descripcion: Mapped[str] = mapped_column(String(300))  # "Pastel Nutella 1kg"
    cantidad: Mapped[int] = mapped_column(Integer, default=1)
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    notas: Mapped[str | None] = mapped_column(Text)  # "Sin fresas", "Con letrero"

    pedido: Mapped["Pedido"] = relationship(back_populates="detalles")
