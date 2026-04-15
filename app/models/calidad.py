"""
Modelos de control de calidad y trazabilidad.
Inspecciones de producto, trazabilidad de lotes y alertas de recall.
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

class EstadoInspeccion(str, enum.Enum):
    PENDIENTE = "pendiente"
    APROBADO = "aprobado"
    RECHAZADO = "rechazado"
    OBSERVACIONES = "observaciones"


# --- Modelos ---

class ChecklistCalidad(Base):
    """Checklist de inspecciones de calidad de produccion."""
    __tablename__ = "checklists_calidad"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    orden_produccion_id: Mapped[int] = mapped_column(ForeignKey("ordenes_produccion.id"))
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    fecha_inspeccion: Mapped[date] = mapped_column(Date)
    inspector_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    estado: Mapped[EstadoInspeccion] = mapped_column(
        SAEnum(EstadoInspeccion), default=EstadoInspeccion.PENDIENTE
    )

    # Controles de calidad (escala 1-5)
    apariencia: Mapped[int | None] = mapped_column(Integer)
    textura: Mapped[int | None] = mapped_column(Integer)
    sabor: Mapped[int | None] = mapped_column(Integer)

    # Controles pasa/falla
    peso_correcto: Mapped[bool] = mapped_column(Boolean, default=False)
    empaque_correcto: Mapped[bool] = mapped_column(Boolean, default=False)
    temperatura_correcta: Mapped[bool] = mapped_column(Boolean, default=False)

    # Mediciones
    peso_muestra: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    temperatura_muestra: Mapped[Decimal | None] = mapped_column(Numeric(5, 1))

    observaciones: Mapped[str | None] = mapped_column(Text)
    foto_url: Mapped[str | None] = mapped_column(Text)
    calificacion_global: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    orden_produccion: Mapped["OrdenProduccion"] = relationship()  # noqa: F821
    producto: Mapped["Producto"] = relationship()  # noqa: F821
    inspector: Mapped["Usuario"] = relationship()  # noqa: F821


class TrazabilidadLote(Base):
    """Registro de uso de lotes de ingredientes en produccion."""
    __tablename__ = "trazabilidad_lotes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lote_ingrediente_id: Mapped[int] = mapped_column(ForeignKey("lotes_ingrediente.id"))
    orden_produccion_id: Mapped[int | None] = mapped_column(
        ForeignKey("ordenes_produccion.id")
    )
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id"))
    cantidad_usada: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    fecha_uso: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    notas: Mapped[str | None] = mapped_column(Text)

    # Relaciones
    lote_ingrediente: Mapped["LoteIngrediente"] = relationship()  # noqa: F821
    orden_produccion: Mapped["OrdenProduccion | None"] = relationship()  # noqa: F821
    producto: Mapped["Producto | None"] = relationship()  # noqa: F821


class AlertaRecall(Base):
    """Alertas de recall / retiro de producto."""
    __tablename__ = "alertas_recall"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lote_ingrediente_id: Mapped[int] = mapped_column(ForeignKey("lotes_ingrediente.id"))
    motivo: Mapped[str] = mapped_column(Text)
    severidad: Mapped[str] = mapped_column(String(20))  # baja, media, alta, critica
    productos_afectados: Mapped[str] = mapped_column(Text)  # JSON list de product IDs
    acciones_tomadas: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="abierta")  # abierta, en_proceso, resuelta
    reportado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relaciones
    lote_ingrediente: Mapped["LoteIngrediente"] = relationship()  # noqa: F821
    reportador: Mapped["Usuario"] = relationship()  # noqa: F821
