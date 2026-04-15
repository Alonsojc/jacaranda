"""
Modelos del módulo CRM y Marketing.
Campañas, encuestas de satisfacción, interacciones y segmentación de clientes.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Date
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SegmentoCliente(str, enum.Enum):
    VIP = "vip"              # Alto valor, compra frecuente
    LEAL = "leal"            # Regular, valor medio
    NUEVO = "nuevo"          # Adquirido recientemente
    EN_RIESGO = "en_riesgo"  # Era activo, se está volviendo inactivo
    DORMIDO = "dormido"      # Inactivo por >60 días
    PERDIDO = "perdido"      # Inactivo por >120 días


class Campana(Base):
    __tablename__ = "campanas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)
    tipo: Mapped[str] = mapped_column(String(50))  # email, whatsapp, push, sms
    segmento_objetivo: Mapped[str | None] = mapped_column(String(20))  # SegmentoCliente value
    mensaje: Mapped[str] = mapped_column(Text)
    fecha_inicio: Mapped[datetime] = mapped_column(Date)
    fecha_fin: Mapped[datetime | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default="borrador")  # borrador, activa, pausada, finalizada
    enviados: Mapped[int] = mapped_column(Integer, default=0)
    abiertos: Mapped[int] = mapped_column(Integer, default=0)
    conversiones: Mapped[int] = mapped_column(Integer, default=0)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class EncuestaSatisfaccion(Base):
    __tablename__ = "encuestas_satisfaccion"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    venta_id: Mapped[int | None] = mapped_column(ForeignKey("ventas.id"))
    calificacion: Mapped[int] = mapped_column(Integer)  # 1-5
    comentario: Mapped[str | None] = mapped_column(Text)
    categoria: Mapped[str] = mapped_column(String(50))  # producto, servicio, ambiente, precio, general
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class InteraccionCliente(Base):
    __tablename__ = "interacciones_cliente"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(50))  # compra, queja, consulta, felicitacion, seguimiento
    canal: Mapped[str] = mapped_column(String(50))  # presencial, whatsapp, telefono, email
    descripcion: Mapped[str] = mapped_column(Text)
    resultado: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
