"""Modelos para ventas a cafeterías con crédito."""

from datetime import date, datetime, timezone
from decimal import Decimal
import enum

from sqlalchemy import (
    Date, DateTime, Enum as SAEnum, ForeignKey, Numeric, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.venta import MetodoPago, TerminalPago


class EstadoCuentaCafeteria(str, enum.Enum):
    PENDIENTE = "pendiente"
    PAGADA = "pagada"
    CANCELADA = "cancelada"


class CafeteriaVenta(Base):
    """Entrega/venta a cafetería, separada del POS diario."""

    __tablename__ = "cafeteria_ventas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folio: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)

    cafeteria_nombre: Mapped[str] = mapped_column(String(200), index=True)
    contacto_nombre: Mapped[str | None] = mapped_column(String(150))
    telefono: Mapped[str | None] = mapped_column(String(30))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    iva_0: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    iva_16: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total_impuestos: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    monto_pagado: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    estado: Mapped[EstadoCuentaCafeteria] = mapped_column(
        SAEnum(EstadoCuentaCafeteria),
        default=EstadoCuentaCafeteria.PENDIENTE,
        index=True,
    )
    fecha: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    fecha_credito: Mapped[date | None] = mapped_column(Date)
    notas: Mapped[str | None] = mapped_column(Text)

    detalles: Mapped[list["DetalleCafeteriaVenta"]] = relationship(
        back_populates="venta",
        cascade="all, delete-orphan",
    )
    pagos: Mapped[list["PagoCafeteriaVenta"]] = relationship(
        back_populates="venta",
        cascade="all, delete-orphan",
    )

    @property
    def saldo_pendiente(self) -> Decimal:
        saldo = Decimal(self.total or 0) - Decimal(self.monto_pagado or 0)
        return max(saldo, Decimal("0"))


class DetalleCafeteriaVenta(Base):
    __tablename__ = "detalles_cafeteria_venta"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("cafeteria_ventas.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)

    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tasa_iva: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    monto_iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    venta: Mapped["CafeteriaVenta"] = relationship(back_populates="detalles")
    producto: Mapped["Producto"] = relationship()  # noqa: F821

    @property
    def producto_nombre(self) -> str | None:
        return self.producto.nombre if self.producto else None


class PagoCafeteriaVenta(Base):
    __tablename__ = "pagos_cafeteria_venta"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("cafeteria_ventas.id"), index=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    metodo_pago: Mapped[MetodoPago] = mapped_column(SAEnum(MetodoPago))
    terminal: Mapped[TerminalPago] = mapped_column(SAEnum(TerminalPago))
    referencia: Mapped[str | None] = mapped_column(String(120))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    fecha: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    venta: Mapped["CafeteriaVenta"] = relationship(back_populates="pagos")
