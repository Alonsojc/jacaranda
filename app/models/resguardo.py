"""Opening checkpoint for the physical cash held in safekeeping."""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ResguardoControl(Base):
    __tablename__ = "resguardo_control"
    __table_args__ = (CheckConstraint("id = 1", name="ck_resguardo_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    saldo_inicial: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    ultimo_corte_id: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_egreso_id: Mapped[int] = mapped_column(Integer, default=0)
    creado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    iniciado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
