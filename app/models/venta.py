"""
Modelos de ventas y punto de venta (POS).
Incluye desglose fiscal para cumplimiento SAT.
"""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, ForeignKey, Text,
    Numeric, Boolean, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class MetodoPago(str, enum.Enum):
    EFECTIVO = "01"           # Clave SAT
    CHEQUE = "02"
    TRANSFERENCIA = "03"
    TARJETA_CREDITO = "04"
    TARJETA_DEBITO = "28"
    VALES_DESPENSA = "08"
    POR_DEFINIR = "99"


class FormaPago(str, enum.Enum):
    PUE = "PUE"  # Pago en Una sola Exhibición
    PPD = "PPD"  # Pago en Parcialidades o Diferido


class TerminalPago(str, enum.Enum):
    EFECTIVO = "efectivo"      # Sin terminal, pago en efectivo
    CLIP = "clip"              # Terminal CLIP (tarjeta)
    BBVA = "bbva"              # Terminal BBVA (tarjeta)


class EstadoVenta(str, enum.Enum):
    COMPLETADA = "completada"
    CANCELADA = "cancelada"
    PENDIENTE = "pendiente"


class Venta(Base):
    __tablename__ = "ventas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folio: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    serie: Mapped[str] = mapped_column(String(5), default="T")  # T=Ticket, A=Factura

    # Relaciones
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))

    # Totales
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    descuento: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    iva_0: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    iva_16: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    ieps: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total_impuestos: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    # Pago
    metodo_pago: Mapped[MetodoPago] = mapped_column(
        SAEnum(MetodoPago), default=MetodoPago.EFECTIVO
    )
    forma_pago: Mapped[FormaPago] = mapped_column(
        SAEnum(FormaPago), default=FormaPago.PUE
    )
    terminal: Mapped[TerminalPago] = mapped_column(
        SAEnum(TerminalPago), default=TerminalPago.EFECTIVO
    )
    monto_recibido: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    cambio: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    # Estado y facturación
    estado: Mapped[EstadoVenta] = mapped_column(
        SAEnum(EstadoVenta), default=EstadoVenta.COMPLETADA
    )
    facturada: Mapped[bool] = mapped_column(Boolean, default=False)

    notas: Mapped[str | None] = mapped_column(Text)
    fecha: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    cliente: Mapped["Cliente | None"] = relationship(back_populates="ventas")  # noqa: F821
    detalles: Mapped[list["DetalleVenta"]] = relationship(
        back_populates="venta", cascade="all, delete-orphan"
    )
    pagos: Mapped[list["PagoVenta"]] = relationship(
        back_populates="venta", cascade="all, delete-orphan"
    )
    cfdi: Mapped["CFDIComprobante | None"] = relationship(  # noqa: F821
        back_populates="venta", foreign_keys="[CFDIComprobante.venta_id]", uselist=False,
    )


class DetalleVenta(Base):
    __tablename__ = "detalles_venta"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))

    cantidad: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    descuento: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    # Desglose fiscal por partida (requerido CFDI 4.0)
    clave_prod_serv_sat: Mapped[str] = mapped_column(String(8))
    clave_unidad_sat: Mapped[str] = mapped_column(String(4))
    tasa_iva: Mapped[Decimal] = mapped_column(Numeric(6, 4), default=Decimal("0"))
    monto_iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    objeto_impuesto: Mapped[str] = mapped_column(String(2), default="02")

    venta: Mapped["Venta"] = relationship(back_populates="detalles")
    producto: Mapped["Producto"] = relationship()  # noqa: F821


class PagoVenta(Base):
    """Pagos individuales de una venta (permite pagos divididos)."""
    __tablename__ = "pagos_venta"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    venta_id: Mapped[int] = mapped_column(ForeignKey("ventas.id"))
    metodo_pago: Mapped[MetodoPago] = mapped_column(SAEnum(MetodoPago))
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    referencia: Mapped[str | None] = mapped_column(String(100))

    venta: Mapped["Venta"] = relationship(back_populates="pagos")


class CorteCaja(Base):
    """Corte de caja diario."""
    __tablename__ = "cortes_caja"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    fondo_inicial: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_ventas_efectivo: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_ventas_tarjeta: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_ventas_transferencia: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_ventas_clip: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total_ventas_bbva: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total_ventas: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    retiros: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    efectivo_esperado: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    efectivo_real: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    diferencia: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    numero_ventas: Mapped[int] = mapped_column(Integer)
    numero_cancelaciones: Mapped[int] = mapped_column(Integer, default=0)

    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
