"""
Modelo de clientes.
Cumple con requisitos de facturación CFDI 4.0 del SAT.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import String, Boolean, DateTime, Date, Text, Numeric, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Datos generales
    nombre: Mapped[str] = mapped_column(String(200))
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))

    # Datos fiscales (requeridos para CFDI 4.0)
    rfc: Mapped[str | None] = mapped_column(String(13), index=True)
    razon_social: Mapped[str | None] = mapped_column(String(300))
    regimen_fiscal: Mapped[str | None] = mapped_column(String(3))  # Clave SAT
    domicilio_fiscal_cp: Mapped[str | None] = mapped_column(String(5))
    uso_cfdi: Mapped[str] = mapped_column(String(4), default="S01")  # Sin efectos fiscales

    # Dirección
    calle: Mapped[str | None] = mapped_column(String(200))
    numero_exterior: Mapped[str | None] = mapped_column(String(20))
    numero_interior: Mapped[str | None] = mapped_column(String(20))
    colonia: Mapped[str | None] = mapped_column(String(100))
    municipio: Mapped[str | None] = mapped_column(String(100))
    estado: Mapped[str | None] = mapped_column(String(50))
    codigo_postal: Mapped[str | None] = mapped_column(String(5))

    # Programa de lealtad
    cliente_frecuente: Mapped[bool] = mapped_column(Boolean, default=False)
    puntos_acumulados: Mapped[int] = mapped_column(default=0)
    nivel_lealtad: Mapped[str] = mapped_column(String(20), default="bronce")  # bronce, plata, oro
    puntos_totales_historicos: Mapped[int] = mapped_column(default=0)  # Para calcular nivel
    monto_lealtad_acumulado: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0")
    )
    recompensas_lealtad_canjeadas: Mapped[int] = mapped_column(Integer, default=0)
    fecha_cumpleanos: Mapped[date | None] = mapped_column(Date)
    tarjeta_qr: Mapped[str | None] = mapped_column(String(100))  # UUID para tarjeta digital
    notas: Mapped[str | None] = mapped_column(Text)

    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    ventas: Mapped[list["Venta"]] = relationship(back_populates="cliente")  # noqa: F821
