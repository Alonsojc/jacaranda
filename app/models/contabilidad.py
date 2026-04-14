"""
Modelos de contabilidad y conciliación bancaria.
Catálogo de cuentas basado en estándar SAT, partida doble,
y movimientos bancarios para conciliación.
"""

from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, ForeignKey, Text,
    Numeric, Boolean, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


# --- Enums ---

class TipoCuenta(str, enum.Enum):
    ACTIVO = "activo"
    PASIVO = "pasivo"
    CAPITAL = "capital"
    INGRESO = "ingreso"
    COSTO = "costo"
    GASTO = "gasto"


class NaturalezaCuenta(str, enum.Enum):
    DEUDORA = "deudora"
    ACREEDORA = "acreedora"


class TipoAsiento(str, enum.Enum):
    DIARIO = "diario"
    INGRESO = "ingreso"
    EGRESO = "egreso"
    NOMINA = "nomina"
    AJUSTE = "ajuste"


# --- Modelos ---

class CuentaContable(Base):
    """Catálogo de cuentas contables (estándar SAT)."""
    __tablename__ = "cuentas_contables"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[TipoCuenta] = mapped_column(SAEnum(TipoCuenta))
    naturaleza: Mapped[NaturalezaCuenta] = mapped_column(SAEnum(NaturalezaCuenta))
    padre_id: Mapped[int | None] = mapped_column(ForeignKey("cuentas_contables.id"))
    nivel: Mapped[int] = mapped_column(Integer)  # 1=grupo, 2=subgrupo, 3=detalle
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    padre: Mapped["CuentaContable | None"] = relationship(
        back_populates="subcuentas", remote_side="CuentaContable.id"
    )
    subcuentas: Mapped[list["CuentaContable"]] = relationship(back_populates="padre")
    lineas: Mapped[list["LineaAsiento"]] = relationship(back_populates="cuenta")


class AsientoContable(Base):
    """Asientos contables (pólizas) de partida doble."""
    __tablename__ = "asientos_contables"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    numero: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    fecha: Mapped[date] = mapped_column(Date)
    concepto: Mapped[str] = mapped_column(String(500))
    tipo: Mapped[TipoAsiento] = mapped_column(SAEnum(TipoAsiento))
    referencia_id: Mapped[int | None] = mapped_column(Integer)
    referencia_tipo: Mapped[str | None] = mapped_column(String(50))  # "venta", "nomina", "compra"
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    aprobado: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    lineas: Mapped[list["LineaAsiento"]] = relationship(
        back_populates="asiento", cascade="all, delete-orphan"
    )


class LineaAsiento(Base):
    """Líneas de asiento contable (debe/haber)."""
    __tablename__ = "lineas_asiento"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    asiento_id: Mapped[int] = mapped_column(ForeignKey("asientos_contables.id"))
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas_contables.id"))
    debe: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    haber: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    concepto: Mapped[str | None] = mapped_column(String(300))

    # Relaciones
    asiento: Mapped["AsientoContable"] = relationship(back_populates="lineas")
    cuenta: Mapped["CuentaContable"] = relationship(back_populates="lineas")


class MovimientoBancario(Base):
    """Movimientos bancarios para conciliación."""
    __tablename__ = "movimientos_bancarios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fecha: Mapped[date] = mapped_column(Date)
    concepto: Mapped[str] = mapped_column(String(300))
    referencia: Mapped[str | None] = mapped_column(String(100))
    deposito: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    retiro: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    saldo: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    conciliado: Mapped[bool] = mapped_column(Boolean, default=False)
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"))
    asiento_id: Mapped[int | None] = mapped_column(ForeignKey("asientos_contables.id"))
    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    venta: Mapped["Venta | None"] = relationship()  # noqa: F821
    asiento: Mapped["AsientoContable | None"] = relationship()
