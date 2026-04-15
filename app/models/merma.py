"""
Modelo de registros de merma (desperdicio/pérdida).
Trazabilidad de pérdidas por caducidad, producción, daño u otros motivos.
"""

from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, ForeignKey, Text,
    Numeric, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


class TipoMerma(str, enum.Enum):
    CADUCIDAD = "caducidad"
    PRODUCCION = "produccion"
    DANO = "dano"
    DEVOLUCION = "devolucion"
    OTRO = "otro"


class RegistroMerma(Base):
    """Registro individual de merma de producto o ingrediente."""
    __tablename__ = "registros_merma"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id"))
    ingrediente_id: Mapped[int | None] = mapped_column(ForeignKey("ingredientes.id"))
    tipo: Mapped[TipoMerma] = mapped_column(SAEnum(TipoMerma))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    unidad_medida: Mapped[str] = mapped_column(String(20))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    costo_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0"))
    motivo: Mapped[str | None] = mapped_column(Text)
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("lotes_ingrediente.id"))
    fecha_merma: Mapped[date] = mapped_column(Date)
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    producto: Mapped["Producto | None"] = relationship()  # noqa: F821
    ingrediente: Mapped["Ingrediente | None"] = relationship()  # noqa: F821
    lote: Mapped["LoteIngrediente | None"] = relationship()  # noqa: F821
    responsable: Mapped["Usuario | None"] = relationship()  # noqa: F821
