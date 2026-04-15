"""
Modelos de multi-sucursal.
Gestión de puntos de venta, inventario por sucursal, traspasos.
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


class EstadoTraspaso(str, enum.Enum):
    SOLICITADO = "solicitado"
    EN_TRANSITO = "en_transito"
    RECIBIDO = "recibido"
    CANCELADO = "cancelado"


class Sucursal(Base):
    """Punto de venta / sucursal."""
    __tablename__ = "sucursales"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    direccion: Mapped[str | None] = mapped_column(Text)
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))

    # Datos fiscales (puede variar por sucursal)
    codigo_postal: Mapped[str | None] = mapped_column(String(5))
    lugar_expedicion: Mapped[str | None] = mapped_column(String(5))

    es_matriz: Mapped[bool] = mapped_column(Boolean, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    inventario: Mapped[list["InventarioSucursal"]] = relationship(
        back_populates="sucursal", cascade="all, delete-orphan"
    )


class InventarioSucursal(Base):
    """Stock de un producto en una sucursal específica."""
    __tablename__ = "inventario_sucursal"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sucursal_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"), index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)

    stock_actual: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    stock_minimo: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))

    sucursal: Mapped["Sucursal"] = relationship(back_populates="inventario")
    producto: Mapped["Producto"] = relationship()  # noqa: F821


class Traspaso(Base):
    """Traspaso de mercancía entre sucursales."""
    __tablename__ = "traspasos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    folio: Mapped[str] = mapped_column(String(30), unique=True, index=True)

    sucursal_origen_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))
    sucursal_destino_id: Mapped[int] = mapped_column(ForeignKey("sucursales.id"))

    estado: Mapped[EstadoTraspaso] = mapped_column(
        SAEnum(EstadoTraspaso), default=EstadoTraspaso.SOLICITADO
    )

    notas: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    recibido_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sucursal_origen: Mapped["Sucursal"] = relationship(foreign_keys=[sucursal_origen_id])
    sucursal_destino: Mapped["Sucursal"] = relationship(foreign_keys=[sucursal_destino_id])
    detalles: Mapped[list["DetalleTraspaso"]] = relationship(
        back_populates="traspaso", cascade="all, delete-orphan"
    )


class DetalleTraspaso(Base):
    """Línea de detalle de un traspaso."""
    __tablename__ = "detalles_traspaso"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    traspaso_id: Mapped[int] = mapped_column(ForeignKey("traspasos.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))

    cantidad_enviada: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    cantidad_recibida: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))

    traspaso: Mapped["Traspaso"] = relationship(back_populates="detalles")
    producto: Mapped["Producto"] = relationship()  # noqa: F821
