"""
Modelos de gestión de proveedores y compras.
Órdenes de compra, recepción de mercancía, cuentas por pagar, evaluaciones.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, ForeignKey, Text,
    Numeric, Boolean, Enum as SAEnum, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class EstadoOrdenCompra(str, enum.Enum):
    BORRADOR = "borrador"
    ENVIADA = "enviada"
    PARCIAL = "parcial"       # Recibida parcialmente
    RECIBIDA = "recibida"
    CANCELADA = "cancelada"


class EstadoCuentaPagar(str, enum.Enum):
    PENDIENTE = "pendiente"
    PARCIAL = "parcial"
    PAGADA = "pagada"
    VENCIDA = "vencida"
    CANCELADA = "cancelada"


class OrdenCompra(Base):
    """Orden de compra a proveedor."""
    __tablename__ = "ordenes_compra"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folio: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    sucursal_id: Mapped[int | None] = mapped_column(ForeignKey("sucursales.id"))

    fecha_emision: Mapped[date] = mapped_column(Date)
    fecha_entrega_esperada: Mapped[date | None] = mapped_column(Date)
    fecha_recepcion: Mapped[date | None] = mapped_column(Date)

    estado: Mapped[EstadoOrdenCompra] = mapped_column(
        SAEnum(EstadoOrdenCompra), default=EstadoOrdenCompra.BORRADOR, index=True
    )

    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    iva: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))

    notas: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    proveedor: Mapped["Proveedor"] = relationship()  # noqa: F821
    detalles: Mapped[list["DetalleOrdenCompra"]] = relationship(
        back_populates="orden", cascade="all, delete-orphan"
    )
    cuenta_pagar: Mapped["CuentaPagar | None"] = relationship(
        back_populates="orden_compra", uselist=False
    )


class DetalleOrdenCompra(Base):
    """Línea de detalle de una orden de compra."""
    __tablename__ = "detalles_orden_compra"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_compra.id"))
    ingrediente_id: Mapped[int] = mapped_column(ForeignKey("ingredientes.id"))

    cantidad_solicitada: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    cantidad_recibida: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    notas: Mapped[str | None] = mapped_column(Text)

    orden: Mapped["OrdenCompra"] = relationship(back_populates="detalles")
    ingrediente: Mapped["Ingrediente"] = relationship()  # noqa: F821


class RecepcionOrdenCompra(Base):
    """Registro idempotente de recepciones de mercancía."""
    __tablename__ = "recepciones_orden_compra"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_recepciones_oc_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    orden_id: Mapped[int] = mapped_column(ForeignKey("ordenes_compra.id"), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    payload_json: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    orden: Mapped["OrdenCompra"] = relationship()


class CuentaPagar(Base):
    """Cuentas por pagar a proveedores."""
    __tablename__ = "cuentas_pagar"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    orden_compra_id: Mapped[int | None] = mapped_column(ForeignKey("ordenes_compra.id"))

    concepto: Mapped[str] = mapped_column(String(300))
    monto_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    monto_pagado: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    saldo_pendiente: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    fecha_factura: Mapped[date] = mapped_column(Date)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, index=True)

    estado: Mapped[EstadoCuentaPagar] = mapped_column(
        SAEnum(EstadoCuentaPagar), default=EstadoCuentaPagar.PENDIENTE, index=True
    )

    numero_factura: Mapped[str | None] = mapped_column(String(50))
    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    proveedor: Mapped["Proveedor"] = relationship()  # noqa: F821
    orden_compra: Mapped["OrdenCompra | None"] = relationship(back_populates="cuenta_pagar")
    pagos: Mapped[list["PagoCuentaPagar"]] = relationship(
        back_populates="cuenta", cascade="all, delete-orphan"
    )


class PagoCuentaPagar(Base):
    """Registro de pagos a cuentas por pagar."""
    __tablename__ = "pagos_cuentas_pagar"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas_pagar.id"))

    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    metodo_pago: Mapped[str] = mapped_column(String(50))  # transferencia, cheque, efectivo
    referencia: Mapped[str | None] = mapped_column(String(100))
    fecha_pago: Mapped[date] = mapped_column(Date)
    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    cuenta: Mapped["CuentaPagar"] = relationship(back_populates="pagos")


class EvaluacionProveedor(Base):
    """Evaluación periódica de proveedor."""
    __tablename__ = "evaluaciones_proveedor"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proveedor_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)

    periodo_inicio: Mapped[date] = mapped_column(Date)
    periodo_fin: Mapped[date] = mapped_column(Date)

    # Métricas (1-5)
    calidad_producto: Mapped[int] = mapped_column(Integer, default=3)
    puntualidad_entrega: Mapped[int] = mapped_column(Integer, default=3)
    precio_competitivo: Mapped[int] = mapped_column(Integer, default=3)
    atencion_servicio: Mapped[int] = mapped_column(Integer, default=3)
    calificacion_global: Mapped[Decimal] = mapped_column(Numeric(3, 1), default=Decimal("3.0"))

    ordenes_evaluadas: Mapped[int] = mapped_column(Integer, default=0)
    entregas_a_tiempo: Mapped[int] = mapped_column(Integer, default=0)
    entregas_completas: Mapped[int] = mapped_column(Integer, default=0)

    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    proveedor: Mapped["Proveedor"] = relationship()  # noqa: F821
