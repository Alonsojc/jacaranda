"""Schemas de inventario: ingredientes, productos, movimientos."""

from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import datetime, date

from app.models.inventario import (
    UnidadMedida, CategoriaProductoEnum, TipoMovimiento, TasaIVA,
)


# --- Categorías ---

class CategoriaCreate(BaseModel):
    nombre: str = Field(..., max_length=100)
    tipo: CategoriaProductoEnum = CategoriaProductoEnum.PAN_DULCE
    descripcion: str | None = None


class CategoriaResponse(BaseModel):
    id: int
    nombre: str
    tipo: CategoriaProductoEnum
    descripcion: str | None
    activo: bool

    model_config = {"from_attributes": True}


# --- Proveedores ---

class ProveedorCreate(BaseModel):
    nombre: str = Field(..., max_length=200)
    rfc: str | None = None
    contacto: str | None = None
    telefono: str | None = None
    email: str | None = None
    direccion: str | None = None
    licencia_sanitaria: str | None = None
    certificaciones: str | None = None


class ProveedorResponse(BaseModel):
    id: int
    nombre: str
    rfc: str | None
    contacto: str | None
    telefono: str | None
    email: str | None
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


# --- Ingredientes ---

class IngredienteCreate(BaseModel):
    nombre: str = Field(..., max_length=150)
    descripcion: str | None = None
    unidad_medida: UnidadMedida
    stock_minimo: Decimal = Field(default=Decimal("0"), ge=0)
    costo_unitario: Decimal = Field(default=Decimal("0"), ge=0)
    proveedor_id: int | None = None
    es_alergeno: bool = False
    tipo_alergeno: str | None = None
    requiere_refrigeracion: bool = False
    temperatura_almacenamiento: str | None = None


class IngredienteUpdate(BaseModel):
    nombre: str | None = None
    costo_unitario: Decimal | None = Field(default=None, ge=0)
    stock_minimo: Decimal | None = Field(default=None, ge=0)
    proveedor_id: int | None = Field(default=None, gt=0)
    activo: bool | None = None


class IngredienteResponse(BaseModel):
    id: int
    nombre: str
    descripcion: str | None
    unidad_medida: UnidadMedida
    stock_actual: Decimal
    stock_minimo: Decimal
    costo_unitario: Decimal
    proveedor_id: int | None
    es_alergeno: bool
    tipo_alergeno: str | None
    requiere_refrigeracion: bool
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


# --- Productos ---

class ProductoCreate(BaseModel):
    codigo: str = Field(..., max_length=50)
    nombre: str = Field(..., max_length=200)
    descripcion: str | None = None
    categoria_id: int | None = None
    precio_unitario: Decimal = Field(..., gt=0)
    costo_produccion: Decimal = Field(default=Decimal("0"), ge=0)
    unidad_medida: UnidadMedida = UnidadMedida.PIEZA
    stock_minimo: Decimal = Field(default=Decimal("0"), ge=0)
    clave_prod_serv_sat: str = "50181900"
    clave_unidad_sat: str = "H87"
    tasa_iva: TasaIVA = TasaIVA.TASA_0
    objeto_impuesto: str = "02"
    vida_util_dias: int | None = None
    requiere_refrigeracion: bool = False
    alergenos: str | None = None

    # NOM-051
    peso_neto_g: Decimal | None = None
    calorias_por_100g: int | None = None
    sodio_mg_por_100g: int | None = None
    azucar_g_por_100g: Decimal | None = None
    grasa_saturada_g_por_100g: Decimal | None = None
    grasa_trans_g_por_100g: Decimal | None = None
    contiene_edulcorantes: bool = False
    contiene_cafeina: bool = False


class ProductoUpdate(BaseModel):
    nombre: str | None = None
    precio_unitario: Decimal | None = Field(default=None, gt=0)
    costo_produccion: Decimal | None = Field(default=None, ge=0)
    tasa_iva: TasaIVA | None = None
    activo: bool | None = None
    stock_minimo: Decimal | None = Field(default=None, ge=0)


class ProductoResponse(BaseModel):
    id: int
    codigo: str
    nombre: str
    descripcion: str | None
    imagen: str | None = None
    categoria_id: int | None
    precio_unitario: Decimal
    costo_produccion: Decimal
    unidad_medida: UnidadMedida
    stock_actual: Decimal
    stock_minimo: Decimal
    tasa_iva: TasaIVA
    clave_prod_serv_sat: str
    alergenos: str | None
    vida_util_dias: int | None
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


# --- Movimientos de inventario ---

class MovimientoCreate(BaseModel):
    tipo: TipoMovimiento
    ingrediente_id: int | None = None
    producto_id: int | None = None
    cantidad: Decimal = Field(..., gt=0)
    costo_unitario: Decimal = Field(default=Decimal("0"), ge=0)
    lote_id: int | None = None
    referencia: str | None = None
    notas: str | None = None


class MovimientoResponse(BaseModel):
    id: int
    tipo: TipoMovimiento
    ingrediente_id: int | None
    producto_id: int | None
    cantidad: Decimal
    costo_unitario: Decimal
    referencia: str | None
    fecha: datetime

    model_config = {"from_attributes": True}


# --- Lotes ---

class LoteCreate(BaseModel):
    ingrediente_id: int
    numero_lote: str
    proveedor_id: int | None = None
    fecha_recepcion: date
    fecha_caducidad: date | None = None
    cantidad: Decimal = Field(..., gt=0)
    costo_unitario: Decimal = Field(..., ge=0)
    temperatura_recepcion: Decimal | None = None
    notas: str | None = None


class LoteResponse(BaseModel):
    id: int
    ingrediente_id: int
    numero_lote: str
    fecha_recepcion: date
    fecha_caducidad: date | None
    cantidad: Decimal
    cantidad_disponible: Decimal
    costo_unitario: Decimal

    model_config = {"from_attributes": True}
