"""Schemas de punto de venta."""

from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
from datetime import datetime

from app.models.venta import MetodoPago, FormaPago, EstadoVenta, TerminalPago


def _cantidad_entera(v) -> int:
    try:
        cantidad = Decimal(str(v))
    except Exception as exc:
        raise ValueError("La cantidad debe ser un entero") from exc
    if cantidad != cantidad.to_integral_value():
        raise ValueError("La cantidad debe ser un entero")
    return int(cantidad)


class DetalleVentaCreate(BaseModel):
    producto_id: int
    cantidad: int = Field(..., gt=0)
    descuento: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("cantidad", mode="before")
    @classmethod
    def validar_cantidad_entera(cls, v) -> int:
        return _cantidad_entera(v)


class PagoVentaCreate(BaseModel):
    metodo_pago: MetodoPago
    terminal: TerminalPago | None = None
    monto: Decimal = Field(..., gt=0)
    referencia: str | None = None


class VentaCreate(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=80)
    cliente_id: int | None = None
    metodo_pago: MetodoPago = MetodoPago.EFECTIVO
    terminal: TerminalPago = TerminalPago.EFECTIVO
    forma_pago: FormaPago = FormaPago.PUE
    monto_recibido: Decimal = Field(default=Decimal("0"), ge=0)
    pago_integrado: bool = False
    referencia_pago: str | None = Field(default=None, max_length=100)
    puntos_canjeados: int = Field(default=0, ge=0)
    canjear_recompensa_lealtad: bool = False
    recompensa_lealtad_motivo: str | None = None
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
    terminal: TerminalPago | None = None
    proveedor: str | None = None
    estado: str = "pagado"
    pago_externo_id: str | None = None
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
    recompensa_lealtad_canjeada: bool = False
    recompensa_lealtad_nombre: str | None = None
    recompensa_lealtad_monto: Decimal = Decimal("0")
    metodo_pago: MetodoPago
    terminal: TerminalPago
    forma_pago: FormaPago
    monto_recibido: Decimal
    cambio: Decimal
    pago_integrado: bool = False
    pago_proveedor: str | None = None
    pago_externo_id: str | None = None
    pago_externo_estado: str | None = None
    pago_externo_referencia: str | None = None
    pago_verificado_en: datetime | None = None
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
    descuento: str | None = None
    iva: str
    total: str
    recompensa_lealtad: dict | None = None
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
