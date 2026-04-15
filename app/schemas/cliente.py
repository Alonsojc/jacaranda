"""Schemas de clientes con validación de RFC."""

from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import date, datetime
import re


class ClienteCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=200)
    telefono: str | None = None
    email: EmailStr | None = None
    rfc: str | None = None
    razon_social: str | None = None
    regimen_fiscal: str | None = None
    domicilio_fiscal_cp: str | None = None
    uso_cfdi: str = "S01"
    calle: str | None = None
    numero_exterior: str | None = None
    numero_interior: str | None = None
    colonia: str | None = None
    municipio: str | None = None
    estado: str | None = None
    codigo_postal: str | None = None
    fecha_cumpleanos: date | None = None
    notas: str | None = None

    @field_validator("rfc")
    @classmethod
    def validar_rfc(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.upper().strip()
        # RFC persona física: 4 letras + 6 dígitos + 3 homoclave = 13
        # RFC persona moral: 3 letras + 6 dígitos + 3 homoclave = 12
        if not re.match(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$", v):
            # Permitir RFC genérico
            if v not in ("XAXX010101000", "XEXX010101000"):
                raise ValueError(
                    "RFC inválido. Formato: 3-4 letras + 6 dígitos fecha + 3 homoclave"
                )
        return v

    @field_validator("regimen_fiscal")
    @classmethod
    def validar_regimen(cls, v: str | None) -> str | None:
        if v is None:
            return v
        regimenes_validos = {
            "601", "603", "605", "606", "607", "608", "610", "611",
            "612", "614", "616", "620", "621", "622", "623", "624",
            "625", "626",
        }
        if v not in regimenes_validos:
            raise ValueError(f"Régimen fiscal '{v}' no válido")
        return v

    @field_validator("domicilio_fiscal_cp")
    @classmethod
    def validar_cp(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^\d{5}$", v):
            raise ValueError("Código postal debe ser de 5 dígitos")
        return v


class ClienteUpdate(BaseModel):
    nombre: str | None = None
    telefono: str | None = None
    email: EmailStr | None = None
    rfc: str | None = None
    razon_social: str | None = None
    regimen_fiscal: str | None = None
    domicilio_fiscal_cp: str | None = None
    uso_cfdi: str | None = None
    activo: bool | None = None


class ClienteResponse(BaseModel):
    id: int
    nombre: str
    telefono: str | None
    email: str | None
    rfc: str | None
    razon_social: str | None
    regimen_fiscal: str | None
    domicilio_fiscal_cp: str | None
    uso_cfdi: str
    puntos_acumulados: int
    nivel_lealtad: str = "bronce"
    puntos_totales_historicos: int = 0
    fecha_cumpleanos: date | None = None
    tarjeta_qr: str | None = None
    notas: str | None = None
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}
