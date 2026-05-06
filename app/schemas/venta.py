"""Schemas de punto de venta."""

from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime

from app.models.venta import MetodoPago, FormaPago, EstadoVenta, TerminalPago


class DetalleVentaCreate(BaseModel):
    producto_id: int
    cantidad: Decimal = Field(..., gt=0)
    descuento: Decimal = Field(default=Decimal("0"), ge=0)


class PagoVentaCreate(BaseModel):
    metodo_pago: MetodoPago
    monto: Decimal = Field(..., gt=0)
    referencia: str | None = None


class VentaCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=80)
    cliente_id: int | None = None
    metodo_pago: MetodoPago = MetodoPago.EFECTIVO
    terminal: TerminalPago = TerminalPago.EFECTIVO
    forma_pago: FormaPago = FormaPago.PUE
    monto_recibido: Decimal = Field(default=Decimal("0"), ge=0)
    puntos_canjeados: int = Field(default=0, ge=0)
    notas: str | None = None
    detalles: list[DetalleVentaCreate] = Field(..., min_length=1)
    pagos: list[PagoVentaCreate] | None = None  # Split payments (optional)


class DetalleVentaResponse(BaseModel):
    id: int
    producto_id: int
    producto_nombre: str | None = None
    cantidad: Decimal
    precio_unitario: Decimal
    descuento: Decimal
    subtotal: Decimal
    tasa_iva: Decimal
    monto_iva: Decimal

    model_config = {"from_attributes": True}


class PagoVentaResponse(BaseModel):
    id: int
    metodo_pago: MetodoPago
    monto: Decimal
    referencia: str | None

    model_config = {"from_attributes": True}


class VentaResponse(BaseModel):
    id: int
    folio: str
    serie: str
    cliente_id: int | None
    subtotal: Decimal
    descuento: Decimal
    iva_0: Decimal
    iva_16: Decimal
    total_impuestos: Decimal
    total: Decimal
    metodo_pago: MetodoPago
    terminal: TerminalPago
    forma_pago: FormaPago
    monto_recibido: Decimal
    cambio: Decimal
    estado: EstadoVenta
    facturada: bool
    fecha: datetime
    detalles: list[DetalleVentaResponse] = Field(default_factory=list)
    pagos: list[PagoVentaResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TicketResponse(BaseModel):
    """Representación del ticket de venta para impresión."""
    razon_social: str
    rfc: str
    direccion: str
    folio: str
    fecha: str
    cajero: str
    productos: list[dict]
    subtotal: str
    iva: str
    total: str
    metodo_pago: str
    monto_recibido: str
    cambio: str
    leyenda_fiscal: str


# --- Corte de caja ---

class CorteCajaCreate(BaseModel):
    fondo_inicial: Decimal = Field(..., ge=0)
    efectivo_real: Decimal = Field(..., ge=0)
    notas: str | None = None
    permitir_repetir: bool = False


class CorteCajaResponse(BaseModel):
    id: int
    fecha: datetime
    fondo_inicial: Decimal
    total_ventas_efectivo: Decimal
    total_ventas_tarjeta: Decimal
    total_ventas_transferencia: Decimal
    total_ventas_clip: Decimal = Decimal("0")
    total_ventas_bbva: Decimal = Decimal("0")
    total_ventas: Decimal
    efectivo_esperado: Decimal
    efectivo_real: Decimal
    diferencia: Decimal
    numero_ventas: int
    numero_cancelaciones: int

    model_config = {"from_attributes": True}


class CorteCajaResumen(BaseModel):
    fecha: str
    total_ventas_efectivo: Decimal
    total_ventas_tarjeta: Decimal
    total_ventas_transferencia: Decimal
    total_ventas_clip: Decimal = Decimal("0")
    total_ventas_bbva: Decimal = Decimal("0")
    total_ventas: Decimal
    efectivo_esperado_base: Decimal
    numero_ventas: int
    numero_cancelaciones: int
    corte_existente: bool
    corte_id: int | None = None
