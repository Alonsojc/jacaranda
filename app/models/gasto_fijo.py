"""Modelo de gastos fijos mensuales (renta, luz, gas, nómina, etc.)."""

from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, Numeric, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GastoFijo(Base):
    __tablename__ = "gastos_fijos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    concepto: Mapped[str] = mapped_column(String(200))
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    periodicidad: Mapped[str] = mapped_column(String(20), default="mensual")  # mensual, quincenal, semanal
    dia_pago: Mapped[int | None] = mapped_column(Integer)  # Día del mes
    notas: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
