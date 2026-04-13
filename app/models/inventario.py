"""
Modelos de inventario: categorías, ingredientes, productos y movimientos.
Incluye trazabilidad por lote para cumplimiento COFEPRIS.
"""

from datetime import datetime, date, timezone
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, ForeignKey, Text,
    Numeric, Boolean, Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from app.core.database import Base


# --- Enums ---

class UnidadMedida(str, enum.Enum):
    KILOGRAMO = "kg"
    GRAMO = "g"
    LITRO = "l"
    MILILITRO = "ml"
    PIEZA = "pz"
    CAJA = "caja"
    BOLSA = "bolsa"
    SACO = "saco"


class CategoriaProductoEnum(str, enum.Enum):
    PAN_BLANCO = "pan_blanco"
    PAN_DULCE = "pan_dulce"
    PAN_SALADO = "pan_salado"
    PASTELERIA = "pasteleria"
    GALLETAS = "galletas"
    REPOSTERIA = "reposteria"
    BEBIDAS = "bebidas"
    OTROS = "otros"


class TipoMovimiento(str, enum.Enum):
    ENTRADA_COMPRA = "entrada_compra"
    ENTRADA_PRODUCCION = "entrada_produccion"
    ENTRADA_DEVOLUCION = "entrada_devolucion"
    ENTRADA_AJUSTE = "entrada_ajuste"
    SALIDA_VENTA = "salida_venta"
    SALIDA_PRODUCCION = "salida_produccion"  # Uso en recetas
    SALIDA_MERMA = "salida_merma"
    SALIDA_AJUSTE = "salida_ajuste"
    SALIDA_CADUCIDAD = "salida_caducidad"


class TasaIVA(str, enum.Enum):
    """Tasas de IVA aplicables según tipo de producto."""
    TASA_0 = "0.00"      # Alimentos básicos no preparados
    TASA_16 = "0.16"     # Alimentos preparados / decorados
    EXENTO = "exento"    # Exento de IVA


# --- Modelos ---

class CategoriaProducto(Base):
    __tablename__ = "categorias_producto"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100), unique=True)
    tipo: Mapped[CategoriaProductoEnum] = mapped_column(
        SAEnum(CategoriaProductoEnum), default=CategoriaProductoEnum.PAN_DULCE
    )
    descripcion: Mapped[str | None] = mapped_column(Text)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    productos: Mapped[list["Producto"]] = relationship(back_populates="categoria")


class Ingrediente(Base):
    """Materias primas e insumos."""
    __tablename__ = "ingredientes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(150), unique=True)
    descripcion: Mapped[str | None] = mapped_column(Text)
    unidad_medida: Mapped[UnidadMedida] = mapped_column(SAEnum(UnidadMedida))
    stock_actual: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    stock_minimo: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))

    # Proveedor principal
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))

    # COFEPRIS / Trazabilidad
    es_alergeno: Mapped[bool] = mapped_column(Boolean, default=False)
    tipo_alergeno: Mapped[str | None] = mapped_column(String(100))  # gluten, lactosa, etc.
    requiere_refrigeracion: Mapped[bool] = mapped_column(Boolean, default=False)
    temperatura_almacenamiento: Mapped[str | None] = mapped_column(String(50))

    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    proveedor: Mapped["Proveedor | None"] = relationship(back_populates="ingredientes")
    movimientos: Mapped[list["MovimientoInventario"]] = relationship(
        back_populates="ingrediente",
        foreign_keys="MovimientoInventario.ingrediente_id",
    )
    receta_ingredientes: Mapped[list["RecetaIngrediente"]] = relationship(  # noqa: F821
        back_populates="ingrediente"
    )


class Producto(Base):
    """Productos terminados para venta."""
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    codigo: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)
    imagen: Mapped[str | None] = mapped_column(Text)  # base64 data URL
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias_producto.id"))

    # Precios
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    costo_produccion: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

    # Inventario
    unidad_medida: Mapped[UnidadMedida] = mapped_column(
        SAEnum(UnidadMedida), default=UnidadMedida.PIEZA
    )
    stock_actual: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    stock_minimo: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))

    # Fiscal - Clave SAT para facturación CFDI
    clave_prod_serv_sat: Mapped[str] = mapped_column(
        String(8), default="50181900"  # Pan y productos de panadería
    )
    clave_unidad_sat: Mapped[str] = mapped_column(
        String(4), default="H87"  # Pieza
    )
    tasa_iva: Mapped[TasaIVA] = mapped_column(
        SAEnum(TasaIVA), default=TasaIVA.TASA_0  # Pan básico 0%
    )
    objeto_impuesto: Mapped[str] = mapped_column(
        String(2), default="02"  # 01=No objeto, 02=Sí objeto, 03=Sí objeto no obligado
    )

    # NOM-051 Etiquetado (para productos empacados)
    peso_neto_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    calorias_por_100g: Mapped[int | None] = mapped_column(Integer)
    sodio_mg_por_100g: Mapped[int | None] = mapped_column(Integer)
    azucar_g_por_100g: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    grasa_saturada_g_por_100g: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    grasa_trans_g_por_100g: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    contiene_edulcorantes: Mapped[bool] = mapped_column(Boolean, default=False)
    contiene_cafeina: Mapped[bool] = mapped_column(Boolean, default=False)

    # COFEPRIS
    alergenos: Mapped[str | None] = mapped_column(String(500))  # Lista separada por comas
    vida_util_dias: Mapped[int | None] = mapped_column(Integer)
    requiere_refrigeracion: Mapped[bool] = mapped_column(Boolean, default=False)

    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relaciones
    categoria: Mapped["CategoriaProducto | None"] = relationship(back_populates="productos")
    receta: Mapped["Receta | None"] = relationship(back_populates="producto")  # noqa: F821
    movimientos: Mapped[list["MovimientoInventario"]] = relationship(
        back_populates="producto",
        foreign_keys="MovimientoInventario.producto_id",
    )


class Proveedor(Base):
    __tablename__ = "proveedores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(200))
    rfc: Mapped[str | None] = mapped_column(String(13))
    contacto: Mapped[str | None] = mapped_column(String(150))
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))
    direccion: Mapped[str | None] = mapped_column(Text)

    # COFEPRIS - Proveedores de insumos alimentarios
    licencia_sanitaria: Mapped[str | None] = mapped_column(String(100))
    certificaciones: Mapped[str | None] = mapped_column(Text)

    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    ingredientes: Mapped[list["Ingrediente"]] = relationship(back_populates="proveedor")


class LoteIngrediente(Base):
    """Trazabilidad de lotes - Requerimiento COFEPRIS."""
    __tablename__ = "lotes_ingrediente"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ingrediente_id: Mapped[int] = mapped_column(ForeignKey("ingredientes.id"))
    numero_lote: Mapped[str] = mapped_column(String(100))
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    fecha_recepcion: Mapped[date] = mapped_column(Date)
    fecha_caducidad: Mapped[date | None] = mapped_column(Date)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    cantidad_disponible: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    temperatura_recepcion: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    notas: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    ingrediente: Mapped["Ingrediente"] = relationship()
    proveedor: Mapped["Proveedor | None"] = relationship()


class MovimientoInventario(Base):
    """Registro de todos los movimientos de inventario."""
    __tablename__ = "movimientos_inventario"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tipo: Mapped[TipoMovimiento] = mapped_column(SAEnum(TipoMovimiento))
    ingrediente_id: Mapped[int | None] = mapped_column(ForeignKey("ingredientes.id"))
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id"))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    costo_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("lotes_ingrediente.id"))
    referencia: Mapped[str | None] = mapped_column(String(200))  # Ej: "Venta #123"
    notas: Mapped[str | None] = mapped_column(Text)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    fecha: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    ingrediente: Mapped["Ingrediente | None"] = relationship(back_populates="movimientos")
    producto: Mapped["Producto | None"] = relationship(back_populates="movimientos")


class HistorialPrecio(Base):
    """Registro de cambios de precio de productos."""
    __tablename__ = "historial_precios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    producto_id: Mapped[int] = mapped_column(ForeignKey("productos.id"), index=True)
    precio_anterior: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    precio_nuevo: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    fecha: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    producto: Mapped["Producto"] = relationship()
