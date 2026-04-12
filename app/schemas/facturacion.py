"""Schemas de facturación CFDI 4.0."""

from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
from datetime import datetime


class CFDIGenerarRequest(BaseModel):
    """Solicitud para generar CFDI a partir de una venta."""
    venta_id: int
    cliente_id: int
    uso_cfdi: str = "S01"
    forma_pago: str = "01"  # Efectivo por default
    metodo_pago: str = "PUE"

    @field_validator("uso_cfdi")
    @classmethod
    def validar_uso(cls, v: str) -> str:
        usos_validos = {
            "G01", "G02", "G03", "I01", "I02", "I03", "I04", "I05",
            "I06", "I07", "I08", "D01", "D02", "D03", "D04", "D05",
            "D06", "D07", "D08", "D09", "D10", "S01", "CP01", "CN01",
        }
        if v not in usos_validos:
            raise ValueError(f"Uso CFDI '{v}' no válido")
        return v


class CFDICancelRequest(BaseModel):
    motivo: str = Field(..., pattern=r"^0[1-4]$")
    uuid_sustitucion: str | None = None  # Requerido si motivo="01"


class CFDIConceptoResponse(BaseModel):
    clave_prod_serv: str
    cantidad: Decimal
    clave_unidad: str
    descripcion: str
    valor_unitario: Decimal
    importe: Decimal
    impuesto_traslado_tasa: Decimal
    impuesto_traslado_importe: Decimal

    model_config = {"from_attributes": True}


class CFDIResponse(BaseModel):
    id: int
    uuid: str | None
    serie: str
    folio: str
    fecha: datetime
    tipo_comprobante: str
    emisor_rfc: str
    emisor_nombre: str
    receptor_rfc: str
    receptor_nombre: str
    receptor_uso_cfdi: str
    subtotal: Decimal
    total_impuestos_trasladados: Decimal
    total: Decimal
    estado: str
    fecha_timbrado: datetime | None
    conceptos: list[CFDIConceptoResponse] = []
    creado_en: datetime

    model_config = {"from_attributes": True}
