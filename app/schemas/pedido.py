"""Schemas para pedidos."""

from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class DetallePedidoCreate(BaseModel):
    descripcion: str
    cantidad: int = Field(default=1, gt=0)
    precio_unitario: Decimal = Field(default=Decimal("0"), ge=0)
    producto_id: int | None = None
    notas: str | None = None


class PedidoCreate(BaseModel):
    cliente_nombre: str
    cliente_telefono: str | None = None
    cliente_id: int | None = None
    fecha_entrega: date
    hora_entrega: str | None = None
    lugar_entrega: str | None = None
    origen: str = "whatsapp"
    anticipo: Decimal = Field(default=Decimal("0"), ge=0)
    notas: str | None = None
    notas_internas: str | None = None
    detalles: list[DetallePedidoCreate]


class PedidoUpdate(BaseModel):
    estado: str | None = None
    hora_entrega: str | None = None
    lugar_entrega: str | None = None
    anticipo: Decimal | None = None
    total: Decimal | None = None
    pagado: bool | None = None
    notas: str | None = None
    notas_internas: str | None = None


class DetallePedidoResponse(BaseModel):
    id: int
    descripcion: str
    cantidad: int
    precio_unitario: Decimal
    notas: str | None
    model_config = {"from_attributes": True}


class PedidoResponse(BaseModel):
    id: int
    folio: str
    cliente_nombre: str
    cliente_telefono: str | None
    fecha_entrega: date
    hora_entrega: str | None
    lugar_entrega: str | None
    estado: str
    origen: str
    anticipo: Decimal
    total: Decimal
    pagado: bool
    notas: str | None
    notas_internas: str | None
    creado_en: datetime
    detalles: list[DetallePedidoResponse]
    model_config = {"from_attributes": True}
