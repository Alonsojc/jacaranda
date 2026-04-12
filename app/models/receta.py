"""
Modelos de recetas y producción.
Permite costeo de productos y planificación de producción.
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


class EstadoProduccion(str, enum.Enum):
    PLANIFICADA = "planificada"
    EN_PROCESO = "en_proceso"
    COMPLETADA = "completada"
    CANCELADA = "cancelada"


class Receta(Base):
    __tablename__ = "recetas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), unique=True)
    nombre: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)
    instrucciones: Mapped[str | None] = mapped_column(Text)
    rendimiento: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # Cantidad producida
    tiempo_preparacion_min: Mapped[int | None] = mapped_column(Integer)
    tiempo_horneado_min: Mapped[int | None] = mapped_column(Integer)
    temperatura_horneado_c: Mapped[int | None] = mapped_column(Integer)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    producto: Mapped["Producto"] = relationship(back_populates="receta")  # noqa: F821
    ingredientes: Mapped[list["RecetaIngrediente"]] = relationship(
        back_populates="receta", cascade="all, delete-orphan"
    )


class RecetaIngrediente(Base):
    __tablename__ = "receta_ingredientes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    receta_id: Mapped[int] = mapped_column(ForeignKey("recetas.id"))
    ingrediente_id: Mapped[int] = mapped_column(ForeignKey("ingredientes.id"))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    notas: Mapped[str | None] = mapped_column(String(200))

    receta: Mapped["Receta"] = relationship(back_populates="ingredientes")
    ingrediente: Mapped["Ingrediente"] = relationship(  # noqa: F821
        back_populates="receta_ingredientes"
    )


class OrdenProduccion(Base):
    """Órdenes de producción para planificación diaria."""
    __tablename__ = "ordenes_produccion"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    receta_id: Mapped[int] = mapped_column(ForeignKey("recetas.id"))
    cantidad_lotes: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("1"))
    estado: Mapped[EstadoProduccion] = mapped_column(
        SAEnum(EstadoProduccion), default=EstadoProduccion.PLANIFICADA
    )
    cantidad_producida: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    cantidad_merma: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("empleados.id"))
    notas: Mapped[str | None] = mapped_column(Text)
    fecha_programada: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fecha_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    receta: Mapped["Receta"] = relationship()
