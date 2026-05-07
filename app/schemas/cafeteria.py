"""Schemas para ventas de cafetería."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.cafeteria import EstadoCuentaCafeteria
from app.models.venta import MetodoPago, TerminalPago


class DetalleCafeteriaCreate(BaseModel):
    producto_id: int = Field(..., gt=0)
    cantidad: Decimal = Field(..., gt=0)


class CafeteriaVentaCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=80)
    cafeteria_nombre: str = Field(..., min_length=1, max_length=200)
    contacto_nombre: str | None = Field(default=None, max_length=150)
    telefono: str | None = Field(default=None, max_length=30)
    dias_credito: int = Field(default=7, ge=0, le=60)
    notas: str | None = None
    detalles: list[DetalleCafeteriaCreate] = Field(..., min_length=1)
    pago_inicial: Decimal | None = Field(default=None, ge=0)
    metodo_pago: MetodoPago = MetodoPago.TRANSFERENCIA
    terminal: TerminalPago = TerminalPago.BBVA
    referencia_pago: str | None = Field(default=None, max_length=120)


class PagoCafeteriaCreate(BaseModel):
    monto: Decimal | None = Field(default=None, gt=0)
    metodo_pago: MetodoPago = MetodoPago.TRANSFERENCIA
    terminal: TerminalPago = TerminalPago.BBVA
    referencia: str | None = Field(default=None, max_length=120)


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
    fecha_credito: date | None
    notas: str | None
    detalles: list[DetalleCafeteriaResponse] = []
    pagos: list[PagoCafeteriaResponse] = []

    model_config = {"from_attributes": True}
