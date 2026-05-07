"""Egresos operativos variables."""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Egreso(Base):
    __tablename__ = "egresos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    concepto: Mapped[str] = mapped_column(String(200), index=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    categoria: Mapped[str] = mapped_column(String(60), default="operativo", index=True)
    metodo_pago: Mapped[str] = mapped_column(String(30), default="efectivo", index=True)
    fecha: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    proveedor: Mapped[str | None] = mapped_column(String(150))
    notas: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    creado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
