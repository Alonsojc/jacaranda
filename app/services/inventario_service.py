"""
Servicio de gestión de inventario.
Control de stock, movimientos, alertas de mínimos y trazabilidad por lote.
"""

from decimal import Decimal
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.inventario import (
    Ingrediente, Producto, MovimientoInventario, LoteIngrediente,
    CategoriaProducto, Proveedor, TipoMovimiento,
)
from app.schemas.inventario import (
    IngredienteCreate, IngredienteUpdate, ProductoCreate, ProductoUpdate,
    MovimientoCreate, LoteCreate, CategoriaCreate, ProveedorCreate,
)


# --- Categorías ---

def crear_categoria(db: Session, data: CategoriaCreate) -> CategoriaProducto:
    categoria = CategoriaProducto(**data.model_dump())
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return categoria


def listar_categorias(db: Session, skip: int = 0, limit: int = 100):
    return db.query(CategoriaProducto).filter(CategoriaProducto.activo.is_(True)).offset(skip).limit(limit).all()


# --- Proveedores ---

def crear_proveedor(db: Session, data: ProveedorCreate) -> Proveedor:
    proveedor = Proveedor(**data.model_dump())
    db.add(proveedor)
    db.commit()
    db.refresh(proveedor)
    return proveedor


def listar_proveedores(db: Session, skip: int = 0, limit: int = 100):
    return db.query(Proveedor).filter(Proveedor.activo.is_(True)).offset(skip).limit(limit).all()


# --- Ingredientes ---

def crear_ingrediente(db: Session, data: IngredienteCreate) -> Ingrediente:
    ingrediente = Ingrediente(**data.model_dump())
    db.add(ingrediente)
    db.commit()
    db.refresh(ingrediente)
    return ingrediente


def actualizar_ingrediente(db: Session, id: int, data: IngredienteUpdate) -> Ingrediente:
    ingrediente = db.query(Ingrediente).filter(Ingrediente.id == id).first()
    if not ingrediente:
        raise ValueError("Ingrediente no encontrado")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(ingrediente, key, value)
    db.commit()
    db.refresh(ingrediente)
    return ingrediente


def listar_ingredientes(db: Session, solo_activos: bool = True, skip: int = 0, limit: int = 100):
    query = db.query(Ingrediente)
    if solo_activos:
        query = query.filter(Ingrediente.activo.is_(True))
    return query.offset(skip).limit(limit).all()


def obtener_ingrediente(db: Session, id: int) -> Ingrediente:
    ingrediente = db.query(Ingrediente).filter(Ingrediente.id == id).first()
    if not ingrediente:
        raise ValueError("Ingrediente no encontrado")
    return ingrediente


def alertas_stock_bajo(db: Session) -> list[dict]:
    """Ingredientes y productos por debajo del stock mínimo."""
    alertas = []

    ingredientes = db.query(Ingrediente).filter(
        and_(
            Ingrediente.activo.is_(True),
            Ingrediente.stock_actual < Ingrediente.stock_minimo,
        )
    ).all()
    for ing in ingredientes:
        alertas.append({
            "tipo": "ingrediente",
            "id": ing.id,
            "nombre": ing.nombre,
            "stock_actual": float(ing.stock_actual),
            "stock_minimo": float(ing.stock_minimo),
            "unidad": ing.unidad_medida.value,
        })

    productos = db.query(Producto).filter(
        and_(
            Producto.activo.is_(True),
            Producto.stock_actual < Producto.stock_minimo,
        )
    ).all()
    for prod in productos:
        alertas.append({
            "tipo": "producto",
            "id": prod.id,
            "nombre": prod.nombre,
            "stock_actual": float(prod.stock_actual),
            "stock_minimo": float(prod.stock_minimo),
            "unidad": prod.unidad_medida.value,
        })

    return alertas


def ingredientes_por_caducar(db: Session, dias: int = 7) -> list[LoteIngrediente]:
    """Lotes de ingredientes que caducan en los próximos N días."""
    from datetime import timedelta
    fecha_limite = date.today() + timedelta(days=dias)
    return db.query(LoteIngrediente).filter(
        and_(
            LoteIngrediente.fecha_caducidad.isnot(None),
            LoteIngrediente.fecha_caducidad <= fecha_limite,
            LoteIngrediente.cantidad_disponible > 0,
        )
    ).all()


# --- Productos ---

def crear_producto(db: Session, data: ProductoCreate) -> Producto:
    if db.query(Producto).filter(Producto.codigo == data.codigo).first():
        raise ValueError(f"Ya existe un producto con código '{data.codigo}'")
    producto = Producto(**data.model_dump())
    db.add(producto)
    db.commit()
    db.refresh(producto)
    return producto


def actualizar_producto(db: Session, id: int, data: ProductoUpdate, usuario_id: int | None = None) -> Producto:
    from app.models.inventario import HistorialPrecio
    producto = db.query(Producto).filter(Producto.id == id).first()
    if not producto:
        raise ValueError("Producto no encontrado")
    updates = data.model_dump(exclude_unset=True)
    # Log price change
    if "precio_unitario" in updates and updates["precio_unitario"] != producto.precio_unitario:
        historial = HistorialPrecio(
            producto_id=id,
            precio_anterior=producto.precio_unitario,
            precio_nuevo=updates["precio_unitario"],
            usuario_id=usuario_id,
        )
        db.add(historial)
    for key, value in updates.items():
        setattr(producto, key, value)
    db.commit()
    db.refresh(producto)
    return producto


def listar_productos(
    db: Session, solo_activos: bool = True,
    q: str | None = None, skip: int = 0, limit: int = 200,
):
    query = db.query(Producto)
    if solo_activos:
        query = query.filter(Producto.activo.is_(True))
    if q:
        query = query.filter(
            Producto.nombre.ilike(f"%{q}%") | Producto.codigo.ilike(f"%{q}%")
        )
    return query.order_by(Producto.nombre).offset(skip).limit(limit).all()


def obtener_producto(db: Session, id: int) -> Producto:
    producto = db.query(Producto).filter(Producto.id == id).first()
    if not producto:
        raise ValueError("Producto no encontrado")
    return producto


# --- Movimientos de inventario ---

def registrar_movimiento(
    db: Session, data: MovimientoCreate, usuario_id: int | None = None,
) -> MovimientoInventario:
    """Registra un movimiento y actualiza el stock correspondiente."""
    movimiento = MovimientoInventario(
        **data.model_dump(), usuario_id=usuario_id,
    )
    db.add(movimiento)

    # Actualizar stock
    es_entrada = data.tipo.value.startswith("entrada")
    cantidad = data.cantidad if es_entrada else -data.cantidad

    if data.ingrediente_id:
        ingrediente = db.query(Ingrediente).filter(
            Ingrediente.id == data.ingrediente_id
        ).first()
        if not ingrediente:
            raise ValueError("Ingrediente no encontrado")
        ingrediente.stock_actual += cantidad
        if ingrediente.stock_actual < 0:
            raise ValueError("Stock insuficiente de ingrediente")
        if es_entrada and data.costo_unitario:
            ingrediente.costo_unitario = data.costo_unitario

    if data.producto_id:
        producto = db.query(Producto).filter(Producto.id == data.producto_id).first()
        if not producto:
            raise ValueError("Producto no encontrado")
        producto.stock_actual += cantidad
        if producto.stock_actual < 0:
            raise ValueError("Stock insuficiente de producto")

    db.commit()
    db.refresh(movimiento)
    return movimiento


def listar_movimientos(
    db: Session, ingrediente_id: int | None = None, producto_id: int | None = None,
    limit: int = 50,
):
    query = db.query(MovimientoInventario)
    if ingrediente_id:
        query = query.filter(MovimientoInventario.ingrediente_id == ingrediente_id)
    if producto_id:
        query = query.filter(MovimientoInventario.producto_id == producto_id)
    return query.order_by(MovimientoInventario.fecha.desc()).limit(limit).all()


# --- Lotes ---

def registrar_lote(db: Session, data: LoteCreate) -> LoteIngrediente:
    """Registra un lote y crea movimiento de entrada."""
    lote = LoteIngrediente(
        **data.model_dump(),
        cantidad_disponible=data.cantidad,
    )
    db.add(lote)

    # Registrar entrada
    movimiento = MovimientoCreate(
        tipo=TipoMovimiento.ENTRADA_COMPRA,
        ingrediente_id=data.ingrediente_id,
        cantidad=data.cantidad,
        costo_unitario=data.costo_unitario,
        referencia=f"Lote {data.numero_lote}",
    )
    registrar_movimiento(db, movimiento)

    db.commit()
    db.refresh(lote)
    return lote
