"""Modelo de conteo diario de inventario (reemplaza el pizarrón del refri)."""

from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, ForeignKey, Text,
    Numeric, Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ConteoInventario(Base):
    """Conteo nocturno de productos terminados."""
    __tablename__ = "conteos_inventario"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))

    # Conteo real (lo que se contó físicamente en la noche)
    cantidad_contada: Mapped[int] = mapped_column(Integer)

    # Calculados por el sistema
    cantidad_inicio_dia: Mapped[int] = mapped_column(Integer, default=0)  # Conteo de la noche anterior
    cantidad_producida: Mapped[int] = mapped_column(Integer, default=0)   # Lo que se horneó
    cantidad_vendida: Mapped[int] = mapped_column(Integer, default=0)     # Ventas del día
    cantidad_esperada: Mapped[int] = mapped_column(Integer, default=0)    # inicio + producida - vendida
    diferencia: Mapped[int] = mapped_column(Integer, default=0)           # contada - esperada

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    notas: Mapped[str | None] = mapped_column(Text)

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    producto: Mapped["Producto"] = relationship()  # noqa: F821
