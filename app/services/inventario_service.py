"""
Servicio de gestión de inventario.
Control de stock, movimientos, alertas de mínimos y trazabilidad por lote.
"""

from decimal import Decimal
from datetime import date
import re
import unicodedata
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.core.time_utils import operation_today
from app.models.inventario import (
    Ingrediente, Producto, MovimientoInventario, LoteIngrediente,
    CategoriaProducto, FamiliaProducto, Proveedor, TipoMovimiento, UnidadMedida,
)
from app.schemas.inventario import (
    IngredienteCreate, IngredienteUpdate, ProductoCreate, ProductoUpdate,
    MovimientoCreate, LoteCreate, CategoriaCreate, ProveedorCreate,
    CompraProductosCreate, EmpaqueCreate, FamiliaProductoCreate, FamiliaProductoUpdate,
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
    values = data.model_dump()
    if data.unidad_medida in {UnidadMedida.CAJA, UnidadMedida.BOLSA}:
        values["es_empaque"] = True
    ingrediente = Ingrediente(**values)
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


def listar_ingredientes(
    db: Session,
    solo_activos: bool = True,
    skip: int = 0,
    limit: int = 100,
    solo_inactivos: bool = False,
):
    query = db.query(Ingrediente)
    if solo_inactivos:
        query = query.filter(Ingrediente.activo.is_(False))
    elif solo_activos:
        query = query.filter(Ingrediente.activo.is_(True))
    return query.offset(skip).limit(limit).all()


def listar_empaques(db: Session, solo_activos: bool = True):
    query = db.query(Ingrediente).filter(Ingrediente.es_empaque.is_(True))
    if solo_activos:
        query = query.filter(Ingrediente.activo.is_(True))
    return query.order_by(Ingrediente.nombre).all()


def crear_empaque(
    db: Session,
    data: EmpaqueCreate,
    usuario_id: int | None = None,
) -> Ingrediente:
    nombre = data.nombre.strip()
    existente = db.query(Ingrediente).filter(
        func.lower(Ingrediente.nombre) == nombre.lower()
    ).first()
    if existente:
        raise ValueError(f"Ya existe un insumo llamado '{existente.nombre}'")

    ingrediente = Ingrediente(
        nombre=nombre,
        unidad_medida=data.unidad_medida,
        stock_actual=Decimal("0"),
        stock_minimo=data.stock_minimo,
        costo_unitario=data.costo_unitario,
        es_empaque=True,
    )
    db.add(ingrediente)
    db.flush()

    if data.stock_actual > 0:
        registrar_movimiento(
            db,
            MovimientoCreate(
                ingrediente_id=ingrediente.id,
                tipo=TipoMovimiento.ENTRADA_AJUSTE,
                cantidad=data.stock_actual,
                costo_unitario=data.costo_unitario,
                referencia="Existencia inicial de caja/empaque",
            ),
            usuario_id,
            commit=False,
        )

    if usuario_id:
        from app.services.auditoria_service import registrar_evento

        registrar_evento(
            db,
            usuario_id=usuario_id,
            usuario_nombre=None,
            accion="crear_empaque",
            modulo="inventario",
            entidad="ingrediente",
            entidad_id=ingrediente.id,
            datos_nuevos={
                "nombre": nombre,
                "unidad_medida": data.unidad_medida.value,
                "stock_actual": data.stock_actual,
                "stock_minimo": data.stock_minimo,
                "costo_unitario": data.costo_unitario,
            },
            commit=False,
        )

    db.commit()
    db.refresh(ingrediente)
    return ingrediente


def obtener_ingrediente(db: Session, id: int) -> Ingrediente:
    ingrediente = db.query(Ingrediente).filter(Ingrediente.id == id).first()
    if not ingrediente:
        raise ValueError("Ingrediente no encontrado")
    return ingrediente


def _ids_empaques_usados(db: Session) -> set[int]:
    rows = db.query(Producto.caja_ingrediente_id).filter(
        Producto.activo.is_(True),
        Producto.caja_ingrediente_id.isnot(None),
    ).all()
    return {int(row[0]) for row in rows if row[0] is not None}


def alertas_stock_bajo(db: Session) -> list[dict]:
    """Ingredientes y productos por debajo del stock mínimo."""
    alertas = []
    empaques_usados = _ids_empaques_usados(db)

    ingredientes = db.query(Ingrediente).filter(
        and_(
            Ingrediente.activo.is_(True),
            (
                (Ingrediente.stock_actual < Ingrediente.stock_minimo)
                | (
                    Ingrediente.id.in_(list(empaques_usados) or [-1])
                    & (Ingrediente.stock_actual <= 0)
                )
            ),
        )
    ).all()
    for ing in ingredientes:
        alertas.append({
            "tipo": "empaque" if ing.id in empaques_usados else "ingrediente",
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


def alertas_empaques(db: Session) -> list[dict]:
    """Empaques/cajas usados por productos que están agotados o debajo del mínimo."""
    productos = db.query(Producto).filter(
        Producto.activo.is_(True),
        Producto.caja_ingrediente_id.isnot(None),
    ).all()
    productos_por_empaque: dict[int, list[Producto]] = {}
    for producto in productos:
        if producto.caja_ingrediente_id is None:
            continue
        productos_por_empaque.setdefault(producto.caja_ingrediente_id, []).append(producto)

    if not productos_por_empaque:
        return []

    ingredientes = db.query(Ingrediente).filter(
        Ingrediente.id.in_(list(productos_por_empaque.keys())),
    ).all()
    alertas = []
    for ingrediente in ingredientes:
        stock = Decimal(str(ingrediente.stock_actual or 0))
        minimo = Decimal(str(ingrediente.stock_minimo or 0))
        if stock > 0 and stock > minimo:
            continue
        productos_ligados = productos_por_empaque.get(ingrediente.id, [])
        alertas.append({
            "tipo": "empaque",
            "id": ingrediente.id,
            "nombre": ingrediente.nombre,
            "stock_actual": float(stock),
            "stock_minimo": float(minimo),
            "unidad": ingrediente.unidad_medida.value,
            "severidad": "sin_stock" if stock <= 0 else "bajo",
            "productos": [
                {
                    "id": producto.id,
                    "nombre": producto.nombre,
                    "caja_cantidad": float(producto.caja_cantidad or 0),
                }
                for producto in productos_ligados
            ],
        })
    alertas.sort(key=lambda item: (item["severidad"] != "sin_stock", item["nombre"]))
    return alertas


def ingredientes_por_caducar(db: Session, dias: int = 7) -> list[LoteIngrediente]:
    """Lotes de ingredientes que caducan en los próximos N días."""
    from datetime import timedelta
    fecha_limite = operation_today() + timedelta(days=dias)
    return db.query(LoteIngrediente).filter(
        and_(
            LoteIngrediente.fecha_caducidad.isnot(None),
            LoteIngrediente.fecha_caducidad <= fecha_limite,
            LoteIngrediente.cantidad_disponible > 0,
        )
    ).all()


# --- Productos ---

_PRESENTACION_RE = re.compile(
    r"^(.+?)\s+(ind\.?|chico|chica|grande|mediano|mediana|mini|x\d+|individual)$",
    re.IGNORECASE,
)


def _limpiar_texto(value: str | None) -> str | None:
    texto = " ".join(str(value or "").strip().split())
    return texto or None


def _separar_familia_presentacion(nombre: str) -> tuple[str, str | None]:
    limpio = _limpiar_texto(nombre) or "Producto"
    match = _PRESENTACION_RE.match(limpio)
    if match:
        return match.group(1), match.group(2)
    return limpio, None


def _familia_por_nombre(db: Session, nombre: str) -> FamiliaProducto | None:
    return (
        db.query(FamiliaProducto)
        .filter(func.lower(FamiliaProducto.nombre) == nombre.lower())
        .first()
    )


def _validar_familia_presentacion(
    db: Session,
    familia_id: int | None,
    presentacion: str | None,
    producto_id: int | None = None,
) -> tuple[int | None, str | None]:
    presentacion_limpia = _limpiar_texto(presentacion)
    if familia_id is None:
        if presentacion_limpia:
            raise ValueError("Selecciona una familia para registrar la presentación")
        return None, None

    familia = db.query(FamiliaProducto).filter(FamiliaProducto.id == familia_id).first()
    if not familia or not familia.activo:
        raise ValueError("La familia seleccionada no existe o está desactivada")
    if not presentacion_limpia:
        raise ValueError("Escribe la presentación, por ejemplo x8, x16 o grande")

    query = db.query(Producto.id).filter(
        Producto.familia_id == familia_id,
        func.lower(Producto.presentacion) == presentacion_limpia.lower(),
    )
    if producto_id is not None:
        query = query.filter(Producto.id != producto_id)
    if query.first():
        raise ValueError(
            f"Ya existe una presentación '{presentacion_limpia}' en la familia '{familia.nombre}'"
        )
    return familia.id, presentacion_limpia


def crear_familia_producto(
    db: Session,
    data: FamiliaProductoCreate,
    usuario_id: int | None = None,
) -> FamiliaProducto:
    from app.services.auditoria_service import registrar_evento

    nombre = _limpiar_texto(data.nombre)
    if not nombre:
        raise ValueError("El nombre de la familia es obligatorio")
    if _familia_por_nombre(db, nombre):
        raise ValueError(f"Ya existe una familia llamada '{nombre}'")
    familia = FamiliaProducto(nombre=nombre)
    db.add(familia)
    db.flush()
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="crear_familia_producto",
        modulo="inventario",
        entidad="familia_producto",
        entidad_id=familia.id,
        datos_nuevos={"nombre": familia.nombre},
        commit=False,
    )
    db.commit()
    db.refresh(familia)
    return familia


def listar_familias_producto(
    db: Session,
    solo_activas: bool = True,
    limit: int = 500,
) -> list[FamiliaProducto]:
    query = db.query(FamiliaProducto)
    if solo_activas:
        query = query.filter(FamiliaProducto.activo.is_(True))
    return query.order_by(FamiliaProducto.nombre).limit(limit).all()


def actualizar_familia_producto(
    db: Session,
    familia_id: int,
    data: FamiliaProductoUpdate,
    usuario_id: int | None = None,
) -> FamiliaProducto:
    from app.services.auditoria_service import registrar_evento

    familia = db.query(FamiliaProducto).filter(FamiliaProducto.id == familia_id).first()
    if not familia:
        raise ValueError("Familia no encontrada")
    updates = data.model_dump(exclude_unset=True)
    nombre = _limpiar_texto(updates.get("nombre")) if "nombre" in updates else None
    if nombre and nombre.lower() != familia.nombre.lower():
        existente = _familia_por_nombre(db, nombre)
        if existente and existente.id != familia.id:
            raise ValueError(f"Ya existe una familia llamada '{nombre}'")
        updates["nombre"] = nombre
    if updates.get("activo") is False:
        hijos_activos = db.query(Producto.id).filter(
            Producto.familia_id == familia.id,
            Producto.activo.is_(True),
        ).first()
        if hijos_activos:
            raise ValueError("No puedes desactivar una familia con presentaciones activas")
    anteriores = {"nombre": familia.nombre, "activo": familia.activo}
    for key, value in updates.items():
        setattr(familia, key, value)
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="actualizar_familia_producto",
        modulo="inventario",
        entidad="familia_producto",
        entidad_id=familia.id,
        datos_anteriores=anteriores,
        datos_nuevos={"nombre": familia.nombre, "activo": familia.activo},
        commit=False,
    )
    db.commit()
    db.refresh(familia)
    return familia


def crear_familia_desde_producto(
    db: Session,
    producto_id: int,
    usuario_id: int | None = None,
) -> Producto:
    from app.services.auditoria_service import registrar_evento

    producto = db.query(Producto).filter(Producto.id == producto_id).first()
    if not producto:
        raise ValueError("Producto no encontrado")
    if producto.familia_id:
        return producto

    nombre_familia, presentacion = _separar_familia_presentacion(producto.nombre)
    if not presentacion:
        # Keeps historic stock and sales when a standalone product becomes
        # the first presentation in a newly created family.
        presentacion = "Original"
    familia = _familia_por_nombre(db, nombre_familia)
    if not familia:
        familia = FamiliaProducto(nombre=nombre_familia)
        db.add(familia)
        db.flush()
    familia_id, presentacion_limpia = _validar_familia_presentacion(
        db,
        familia.id,
        presentacion,
        producto.id,
    )
    producto.familia_id = familia_id
    producto.presentacion = presentacion_limpia
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="vincular_producto_familia",
        modulo="inventario",
        entidad="producto",
        entidad_id=producto.id,
        datos_anteriores={"familia_id": None, "presentacion": None},
        datos_nuevos={
            "familia_id": familia_id,
            "familia": familia.nombre,
            "presentacion": presentacion_limpia,
        },
        commit=False,
    )
    db.commit()
    db.refresh(producto)
    return producto


def _validar_caja_ingrediente(
    db: Session,
    ingrediente_id: int | None,
    caja_cantidad: Decimal | None = None,
) -> None:
    if ingrediente_id is None:
        return
    ingrediente = db.query(Ingrediente).filter(Ingrediente.id == ingrediente_id).first()
    if not ingrediente or not ingrediente.activo:
        raise ValueError("Caja/empaque no encontrado o inactivo")
    if ingrediente.unidad_medida not in (
        UnidadMedida.CAJA,
        UnidadMedida.BOLSA,
        UnidadMedida.PIEZA,
    ):
        raise ValueError("El empaque debe usar unidad caja, bolsa o pieza")
    if not ingrediente.es_empaque:
        if ingrediente.unidad_medida in (UnidadMedida.CAJA, UnidadMedida.BOLSA):
            ingrediente.es_empaque = True
        else:
            raise ValueError("Selecciona un insumo marcado como caja/empaque")
    if caja_cantidad is not None and Decimal(str(caja_cantidad)) <= 0:
        raise ValueError("La cantidad de cajas/empaques por pieza debe ser mayor a cero")


def crear_producto(
    db: Session,
    data: ProductoCreate,
    usuario_id: int | None = None,
) -> Producto:
    codigo = data.codigo.strip().upper()
    if db.query(Producto).filter(func.upper(Producto.codigo) == codigo).first():
        raise ValueError(f"Ya existe un producto con código '{data.codigo}'")
    _validar_caja_ingrediente(db, data.caja_ingrediente_id, data.caja_cantidad)
    values = data.model_dump(exclude={"codigo"})
    familia_id, presentacion = _validar_familia_presentacion(
        db,
        values.get("familia_id"),
        values.get("presentacion"),
    )
    values["familia_id"] = familia_id
    values["presentacion"] = presentacion
    producto = Producto(**values, codigo=codigo)
    db.add(producto)
    db.commit()
    db.refresh(producto)
    return producto


def actualizar_producto(db: Session, id: int, data: ProductoUpdate, usuario_id: int | None = None) -> Producto:
    from app.models.inventario import HistorialPrecio
    from app.services.auditoria_service import registrar_evento
    producto = db.query(Producto).filter(Producto.id == id).first()
    if not producto:
        raise ValueError("Producto no encontrado")
    updates = data.model_dump(exclude_unset=True)
    caja_id = updates.get("caja_ingrediente_id", producto.caja_ingrediente_id)
    caja_cantidad = updates.get("caja_cantidad", producto.caja_cantidad)
    if "caja_ingrediente_id" in updates or "caja_cantidad" in updates:
        _validar_caja_ingrediente(db, caja_id, caja_cantidad)
    if "familia_id" in updates or "presentacion" in updates:
        familia_id, presentacion = _validar_familia_presentacion(
            db,
            updates.get("familia_id", producto.familia_id),
            updates.get("presentacion", producto.presentacion),
            producto.id,
        )
        updates["familia_id"] = familia_id
        updates["presentacion"] = presentacion
    # Log price change
    if "precio_unitario" in updates and updates["precio_unitario"] != producto.precio_unitario:
        historial = HistorialPrecio(
            producto_id=id,
            precio_anterior=producto.precio_unitario,
            precio_nuevo=updates["precio_unitario"],
            usuario_id=usuario_id,
        )
        db.add(historial)
    if (
        "precio_cafeteria" in updates
        and updates["precio_cafeteria"] != producto.precio_cafeteria
    ):
        registrar_evento(
            db,
            usuario_id=usuario_id,
            usuario_nombre=None,
            accion="actualizar_precio_cafeteria",
            modulo="inventario",
            entidad="producto",
            entidad_id=producto.id,
            datos_anteriores={"precio_cafeteria": producto.precio_cafeteria},
            datos_nuevos={
                "precio_cafeteria": updates["precio_cafeteria"],
                "producto": producto.nombre,
            },
            commit=False,
        )
    if (
        "precio_uber_eats" in updates
        and updates["precio_uber_eats"] != producto.precio_uber_eats
    ):
        registrar_evento(
            db,
            usuario_id=usuario_id,
            usuario_nombre=None,
            accion="actualizar_precio_uber_eats",
            modulo="inventario",
            entidad="producto",
            entidad_id=producto.id,
            datos_anteriores={"precio_uber_eats": producto.precio_uber_eats},
            datos_nuevos={
                "precio_uber_eats": updates["precio_uber_eats"],
                "producto": producto.nombre,
            },
            commit=False,
        )
    if "familia_id" in updates or "presentacion" in updates:
        familia_anterior = producto.familia.nombre if producto.familia else None
        familia_nueva = None
        if updates.get("familia_id"):
            familia_obj = db.query(FamiliaProducto).filter(
                FamiliaProducto.id == updates["familia_id"]
            ).first()
            familia_nueva = familia_obj.nombre if familia_obj else None
        registrar_evento(
            db,
            usuario_id=usuario_id,
            usuario_nombre=None,
            accion="actualizar_familia_producto",
            modulo="inventario",
            entidad="producto",
            entidad_id=producto.id,
            datos_anteriores={
                "familia_id": producto.familia_id,
                "familia": familia_anterior,
                "presentacion": producto.presentacion,
            },
            datos_nuevos={
                "familia_id": updates.get("familia_id"),
                "familia": familia_nueva,
                "presentacion": updates.get("presentacion"),
            },
            commit=False,
        )
    for key, value in updates.items():
        setattr(producto, key, value)
    db.commit()
    db.refresh(producto)
    return producto


def listar_productos(
    db: Session, solo_activos: bool = True,
    q: str | None = None, skip: int = 0, limit: int = 200,
    solo_inactivos: bool = False,
):
    query = db.query(Producto)
    if solo_inactivos:
        query = query.filter(Producto.activo.is_(False))
    elif solo_activos:
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


def codigo_producto_disponible(
    db: Session,
    codigo: str,
    exclude_id: int | None = None,
) -> tuple[str, bool]:
    normalizado = str(codigo or "").strip().upper()
    if not normalizado:
        raise ValueError("Escribe un código")
    query = db.query(Producto.id).filter(func.upper(Producto.codigo) == normalizado)
    if exclude_id is not None:
        query = query.filter(Producto.id != exclude_id)
    return normalizado, query.first() is None


def sugerir_codigo_producto(
    db: Session,
    nombre: str | None = None,
    codigo_base: str | None = None,
) -> dict:
    base_limpia = str(codigo_base or "").strip().upper()
    if base_limpia:
        match = re.match(r"^(.+?)(?:[-_ ](\d+))?$", base_limpia)
        prefijo_original = match.group(1) if match else base_limpia
    else:
        texto = str(nombre or "").strip()
        texto = re.sub(
            r"\s+(?:ind\.?|chic[oa]|grande|median[oa]|mini|x\d+|individual)$",
            "",
            texto,
            flags=re.IGNORECASE,
        )
        ascii_texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
        palabras = re.findall(r"[A-Za-z0-9]+", ascii_texto.upper())
        if len(palabras) >= 2:
            prefijo_original = "".join(palabra[0] for palabra in palabras[:4])
        elif palabras:
            prefijo_original = palabras[0][:3]
        else:
            prefijo_original = "PR"

    prefijo = re.sub(r"[^A-Z0-9]+", "-", prefijo_original).strip("-")[:12] or "PR"
    patron = re.compile(rf"^{re.escape(prefijo)}-(\d+)$", re.IGNORECASE)
    numeros = []
    for (codigo,) in db.query(Producto.codigo).filter(
        func.upper(Producto.codigo).like(f"{prefijo}-%")
    ).all():
        encontrado = patron.match(str(codigo or "").strip())
        if encontrado:
            numeros.append(int(encontrado.group(1)))
    siguiente = max(numeros, default=0) + 1
    sugerido = f"{prefijo}-{siguiente:03d}"
    while not codigo_producto_disponible(db, sugerido)[1]:
        siguiente += 1
        sugerido = f"{prefijo}-{siguiente:03d}"
    return {"codigo": sugerido, "prefijo": prefijo, "disponible": True}


# --- Movimientos de inventario ---

def registrar_movimiento(
    db: Session,
    data: MovimientoCreate,
    usuario_id: int | None = None,
    commit: bool = True,
    permitir_stock_negativo: bool = False,
) -> MovimientoInventario:
    """Registra un movimiento y actualiza el stock correspondiente."""
    targets = [data.ingrediente_id is not None, data.producto_id is not None]
    if sum(targets) != 1:
        raise ValueError("Debe especificar exactamente un ingrediente o producto")

    # Actualizar stock
    es_entrada = data.tipo.value.startswith("entrada")
    cantidad = data.cantidad if es_entrada else -data.cantidad
    movimiento_data = data.model_dump()
    es_merma = data.tipo in (
        TipoMovimiento.SALIDA_MERMA,
        TipoMovimiento.SALIDA_CADUCIDAD,
    )

    if data.ingrediente_id is not None:
        ingrediente = db.query(Ingrediente).filter(
            Ingrediente.id == data.ingrediente_id
        ).with_for_update().first()
        if not ingrediente:
            raise ValueError("Ingrediente no encontrado")
        nuevo_stock = ingrediente.stock_actual + cantidad
        if nuevo_stock < 0 and not permitir_stock_negativo:
            raise ValueError("Stock insuficiente de ingrediente")
        ingrediente.stock_actual = nuevo_stock
        if es_entrada and data.costo_unitario:
            ingrediente.costo_unitario = data.costo_unitario
        if es_merma and not data.costo_unitario:
            movimiento_data["costo_unitario"] = ingrediente.costo_unitario or Decimal("0")

    if data.producto_id is not None:
        producto = db.query(Producto).filter(
            Producto.id == data.producto_id
        ).with_for_update().first()
        if not producto:
            raise ValueError("Producto no encontrado")
        nuevo_stock = producto.stock_actual + cantidad
        if nuevo_stock < 0 and not permitir_stock_negativo:
            raise ValueError("Stock insuficiente de producto")
        producto.stock_actual = nuevo_stock
        if es_merma and not data.costo_unitario:
            movimiento_data["costo_unitario"] = producto.costo_produccion or Decimal("0")

    movimiento = MovimientoInventario(
        **movimiento_data, usuario_id=usuario_id,
    )
    db.add(movimiento)
    db.flush()
    if usuario_id:
        from app.services.auditoria_service import registrar_evento

        registrar_evento(
            db,
            usuario_id=usuario_id,
            usuario_nombre=None,
            accion=data.tipo.value,
            modulo="inventario",
            entidad="movimiento_inventario",
            entidad_id=movimiento.id,
            datos_nuevos={
                "ingrediente_id": data.ingrediente_id,
                "producto_id": data.producto_id,
                "cantidad": data.cantidad,
                "costo_unitario": movimiento_data["costo_unitario"],
                "referencia": data.referencia,
                "notas": data.notas,
            },
            commit=False,
        )

    if commit:
        db.commit()
        db.refresh(movimiento)
    return movimiento


def registrar_compra_productos(
    db: Session,
    data: CompraProductosCreate,
    usuario_id: int | None = None,
) -> dict:
    """Registra una compra masiva de producto terminado en una transacción."""
    producto_ids = [item.producto_id for item in data.items]
    if len(producto_ids) != len(set(producto_ids)):
        raise ValueError("Cada producto debe aparecer una sola vez en la compra")

    productos = (
        db.query(Producto)
        .filter(
            Producto.id.in_(producto_ids),
            Producto.activo.is_(True),
        )
        .order_by(Producto.id)
        .with_for_update()
        .all()
    )
    productos_por_id = {producto.id: producto for producto in productos}
    faltantes = sorted(set(producto_ids) - set(productos_por_id))
    if faltantes:
        raise ValueError(
            "Productos no encontrados o inactivos: "
            + ", ".join(str(producto_id) for producto_id in faltantes)
        )

    referencia = (data.referencia or "").strip() or "Compra de productos terminados"
    notas = (data.notas or "").strip() or None
    detalles = []
    stocks_anteriores = {}
    total_piezas = 0

    for item in data.items:
        producto = productos_por_id[item.producto_id]
        stock_anterior = Decimal(str(producto.stock_actual or 0))
        stocks_anteriores[str(producto.id)] = str(stock_anterior)
        registrar_movimiento(
            db,
            MovimientoCreate(
                tipo=TipoMovimiento.ENTRADA_COMPRA,
                producto_id=producto.id,
                cantidad=Decimal(item.cantidad),
                costo_unitario=Decimal(str(producto.costo_produccion or 0)),
                referencia=referencia,
                notas=notas,
            ),
            usuario_id,
            commit=False,
        )
        total_piezas += item.cantidad
        detalles.append({
            "producto_id": producto.id,
            "producto_nombre": producto.nombre,
            "cantidad": item.cantidad,
            "stock_anterior": stock_anterior,
            "stock_nuevo": Decimal(str(producto.stock_actual or 0)),
        })

    from app.services.auditoria_service import registrar_evento

    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="registrar_compra_productos",
        modulo="inventario",
        entidad="compra_productos",
        datos_anteriores={"stocks": stocks_anteriores},
        datos_nuevos={
            "referencia": referencia,
            "notas": notas,
            "total_productos": len(detalles),
            "total_piezas": total_piezas,
            "stocks": {
                str(detalle["producto_id"]): str(detalle["stock_nuevo"])
                for detalle in detalles
            },
        },
        commit=False,
    )
    db.commit()

    return {
        "mensaje": "Compra de productos registrada",
        "total_productos": len(detalles),
        "total_piezas": total_piezas,
        "detalles": detalles,
    }


def registrar_empaque_producto(
    db: Session,
    producto: Producto,
    cantidad_productos: Decimal,
    referencia: str,
    usuario_id: int | None = None,
    *,
    tipo: TipoMovimiento = TipoMovimiento.SALIDA_VENTA,
    commit: bool = False,
    permitir_stock_negativo: bool = True,
) -> MovimientoInventario | None:
    """Registra consumo/devolución del empaque ligado a un producto."""
    caja_id = producto.caja_ingrediente_id
    caja_cantidad = Decimal(str(producto.caja_cantidad or 0))
    cantidad_productos = Decimal(str(cantidad_productos or 0))
    if not caja_id or caja_cantidad <= 0 or cantidad_productos <= 0:
        return None
    _validar_caja_ingrediente(db, caja_id, caja_cantidad)
    return registrar_movimiento(
        db,
        MovimientoCreate(
            tipo=tipo,
            ingrediente_id=caja_id,
            cantidad=caja_cantidad * cantidad_productos,
            referencia=referencia,
            notas=f"Empaque para {producto.nombre}",
        ),
        usuario_id,
        commit=commit,
        permitir_stock_negativo=permitir_stock_negativo,
    )


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
    registrar_movimiento(db, movimiento, commit=False)

    db.commit()
    db.refresh(lote)
    return lote
