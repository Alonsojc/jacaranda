"""Schemas para pedidos."""

from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, model_validator


class DetallePedidoCreate(BaseModel):
    descripcion: str
    cantidad: int = Field(default=1, gt=0)
    precio_unitario: Decimal = Field(default=Decimal("0"), ge=0)
    producto_id: int | None = None
    notas: str | None = None


class PedidoCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=80)
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

    @model_validator(mode="after")
    def validar_fecha_y_detalles(self):
        if self.fecha_entrega < date.today():
            raise ValueError("La fecha de entrega no puede estar en el pasado")
        if not self.detalles:
            raise ValueError("El pedido debe tener al menos un detalle")
        return self


class PedidoUpdate(BaseModel):
    estado: str | None = None
    hora_entrega: str | None = None
    lugar_entrega: str | None = None
    anticipo: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, ge=0)
    pagado: bool | None = None
    notas: str | None = None
    notas_internas: str | None = None
    repartidor_nombre: str | None = None
    repartidor_telefono: str | None = None
    direccion_entrega: str | None = None
    referencia_entrega: str | None = None
    costo_envio: Decimal | None = Field(default=None, ge=0)


class PedidoEstadoUpdate(BaseModel):
    estado: str


class PedidoPagoUpdate(BaseModel):
    pagado: bool
    motivo: str | None = None


class DetallePedidoResponse(BaseModel):
    id: int
    producto_id: int | None
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
    repartidor_nombre: str | None
    repartidor_telefono: str | None
    direccion_entrega: str | None
    referencia_entrega: str | None
    costo_envio: Decimal
    en_ruta_en: datetime | None
    entregado_en: datetime | None
    creado_en: datetime
    detalles: list[DetallePedidoResponse]
    model_config = {"from_attributes": True}
