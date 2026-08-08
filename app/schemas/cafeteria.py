"""Schemas para ventas de cafetería."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.cafeteria import EstadoCuentaCafeteria
from app.models.venta import MetodoPago, TerminalPago


def _cantidad_entera(v) -> int:
    try:
        cantidad = Decimal(str(v))
    except Exception as exc:
        raise ValueError("La cantidad debe ser un entero") from exc
    if cantidad != cantidad.to_integral_value():
        raise ValueError("La cantidad debe ser un entero")
    return int(cantidad)


class DetalleCafeteriaCreate(BaseModel):
    producto_id: int = Field(..., gt=0)
    cantidad: int = Field(..., gt=0)

    @field_validator("cantidad", mode="before")
    @classmethod
    def validar_cantidad_entera(cls, v) -> int:
        return _cantidad_entera(v)


class CafeteriaVentaCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=80)
    cafeteria_id: int | None = Field(default=None, gt=0)
    cafeteria_nombre: str = Field(..., min_length=1, max_length=200)
    contacto_nombre: str | None = Field(default=None, max_length=150)
    telefono: str | None = Field(default=None, max_length=30)
    dias_credito: int = Field(default=7, ge=0, le=60)
    notas: str | None = None
    detalles: list[DetalleCafeteriaCreate] = Field(..., min_length=1)
    pago_inicial: Decimal | None = Field(default=None, ge=0)
    metodo_pago: MetodoPago = MetodoPago.TRANSFERENCIA
    terminal: TerminalPago = TerminalPago.EFECTIVO
    referencia_pago: str | None = Field(default=None, max_length=120)
    iva_factura_tasa: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("0.08"))

    @field_validator("iva_factura_tasa", mode="before")
    @classmethod
    def validar_iva_factura_tasa(cls, v) -> Decimal:
        if v in (None, ""):
            return Decimal("0")
        try:
            tasa = Decimal(str(v))
        except Exception as exc:
            raise ValueError("La tasa de IVA para factura debe ser 0% u 8%") from exc
        if tasa not in {Decimal("0.00"), Decimal("0.08")}:
            raise ValueError("La tasa de IVA para factura debe ser 0% u 8%")
        return tasa.quantize(Decimal("0.01"))


class PagoCafeteriaCreate(BaseModel):
    monto: Decimal | None = Field(default=None, gt=0)
    metodo_pago: MetodoPago = MetodoPago.TRANSFERENCIA
    terminal: TerminalPago = TerminalPago.EFECTIVO
    referencia: str | None = Field(default=None, max_length=120)
    motivo: str | None = Field(default=None, max_length=200)


class CafeteriaClienteCreate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    contacto_nombre: str | None = Field(default=None, max_length=150)
    telefono: str | None = Field(default=None, max_length=30)
    dias_credito: int = Field(default=7, ge=0, le=60)


class CafeteriaClienteUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    contacto_nombre: str | None = Field(default=None, max_length=150)
    telefono: str | None = Field(default=None, max_length=30)
    dias_credito: int | None = Field(default=None, ge=0, le=60)
    activo: bool | None = None


class CafeteriaClienteResponse(BaseModel):
    id: int
    nombre: str
    contacto_nombre: str | None
    telefono: str | None
    dias_credito: int
    activo: bool
    creado_en: datetime
    actualizado_en: datetime

    model_config = {"from_attributes": True}


class DetalleCafeteriaResponse(BaseModel):
    id: int
    producto_id: int
    producto_nombre: str | None = None
    cantidad: Decimal
    precio_unitario: Decimal
    subtotal: Decimal
    tasa_iva: Decimal
    monto_iva: Decimal

    model_config = {"from_attributes": True}


class PagoCafeteriaResponse(BaseModel):
    id: int
    monto: Decimal
    metodo_pago: MetodoPago
    terminal: TerminalPago
    referencia: str | None
    fecha: datetime

    model_config = {"from_attributes": True}


class CafeteriaVentaResponse(BaseModel):
    id: int
    folio: str
    cafeteria_id: int | None
    cafeteria_nombre: str
    contacto_nombre: str | None
    telefono: str | None
    subtotal: Decimal
    iva_0: Decimal
    iva_16: Decimal
    total_impuestos: Decimal
    total: Decimal
    monto_pagado: Decimal
    saldo_pendiente: Decimal
    estado: EstadoCuentaCafeteria
    fecha: datetime
    dias_credito: int
    fecha_credito: date | None
    actualizado_en: datetime
    notas: str | None
    detalles: list[DetalleCafeteriaResponse] = []
    pagos: list[PagoCafeteriaResponse] = []

    model_config = {"from_attributes": True}
