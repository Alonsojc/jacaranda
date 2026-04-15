"""
Modelos del sistema de lealtad avanzado.
Niveles, cupones, promociones, tarjeta digital.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, ForeignKey, Text,
    Numeric, Boolean, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class NivelLealtad(str, enum.Enum):
    BRONCE = "bronce"
    PLATA = "plata"
    ORO = "oro"


class TipoCupon(str, enum.Enum):
    PORCENTAJE = "porcentaje"    # 10% de descuento
    MONTO_FIJO = "monto_fijo"   # $50 de descuento
    PRODUCTO_GRATIS = "producto_gratis"
    PUNTOS_EXTRA = "puntos_extra"  # 2x puntos


class EstadoCupon(str, enum.Enum):
    ACTIVO = "activo"
    USADO = "usado"
    EXPIRADO = "expirado"
    CANCELADO = "cancelado"


class Cupon(Base):
    """Cupones y promociones."""
    __tablename__ = "cupones"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)

    tipo: Mapped[TipoCupon] = mapped_column(SAEnum(TipoCupon))
    valor: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # % o monto según tipo
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id"))

    # Restricciones
    compra_minima: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    nivel_requerido: Mapped[NivelLealtad | None] = mapped_column(SAEnum(NivelLealtad))
    max_usos: Mapped[int] = mapped_column(Integer, default=1)
    usos_actuales: Mapped[int] = mapped_column(Integer, default=0)

    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_fin: Mapped[date] = mapped_column(Date)

    estado: Mapped[EstadoCupon] = mapped_column(
        SAEnum(EstadoCupon), default=EstadoCupon.ACTIVO
    )
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CuponCliente(Base):
    """Asignación de cupones a clientes específicos."""
    __tablename__ = "cupones_cliente"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cupon_id: Mapped[int] = mapped_column(ForeignKey("cupones.id"))
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))

    usado: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_uso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"))

    asignado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    cupon: Mapped["Cupon"] = relationship()
    cliente: Mapped["Cliente"] = relationship()  # noqa: F821


class HistorialPuntos(Base):
    """Historial de movimientos de puntos del cliente."""
    __tablename__ = "historial_puntos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)

    puntos: Mapped[int] = mapped_column(Integer)  # Positivo=ganados, negativo=canjeados
    concepto: Mapped[str] = mapped_column(String(200))
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"))

    saldo_anterior: Mapped[int] = mapped_column(Integer)
    saldo_nuevo: Mapped[int] = mapped_column(Integer)

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
