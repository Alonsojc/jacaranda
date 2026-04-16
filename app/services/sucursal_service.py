"""
Servicio de gestión multi-sucursal.
Sucursales, inventario por sucursal, traspasos entre sucursales.
"""

from datetime import datetime, timezone, date
from decimal import Decimal
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func

from app.models.sucursal import (
    Sucursal, InventarioSucursal, Traspaso, DetalleTraspaso, EstadoTraspaso,
)
from app.models.inventario import Producto


# --- Sucursales ---

def crear_sucursal(db: Session, data: dict) -> Sucursal:
    """Crea una sucursal. La primera creada se marca como matriz."""
    existentes = db.query(Sucursal).count()
    if existentes == 0:
        data["es_matriz"] = True

    if db.query(Sucursal).filter(Sucursal.codigo == data["codigo"]).first():
        raise ValueError(f"Ya existe una sucursal con código '{data['codigo']}'")

    sucursal = Sucursal(**data)
    db.add(sucursal)
    db.commit()
    db.refresh(sucursal)
    return sucursal


def listar_sucursales(db: Session, solo_activas: bool = True, skip: int = 0, limit: int = 100) -> list[Sucursal]:
    query = db.query(Sucursal)
    if solo_activas:
        query = query.filter(Sucursal.activo.is_(True))
    return query.order_by(Sucursal.es_matriz.desc(), Sucursal.nombre).offset(skip).limit(limit).all()


def obtener_sucursal(db: Session, id: int) -> dict:
    """Obtiene sucursal con resumen de inventario."""
    sucursal = db.query(Sucursal).filter(Sucursal.id == id).first()
    if not sucursal:
        raise ValueError("Sucursal no encontrada")

    # Resumen de inventario
    inv_stats = db.query(
        func.count(InventarioSucursal.id).label("total_productos"),
        func.coalesce(func.sum(InventarioSucursal.stock_actual), Decimal("0")).label("total_stock"),
    ).filter(InventarioSucursal.sucursal_id == id).first()

    # Productos bajo mínimo
    bajo_minimo = db.query(func.count(InventarioSucursal.id)).filter(
        and_(
            InventarioSucursal.sucursal_id == id,
            InventarioSucursal.stock_actual < InventarioSucursal.stock_minimo,
        )
    ).scalar()

    return {
        "id": sucursal.id,
        "codigo": sucursal.codigo,
        "nombre": sucursal.nombre,
        "direccion": sucursal.direccion,
        "telefono": sucursal.telefono,
        "email": sucursal.email,
        "codigo_postal": sucursal.codigo_postal,
        "lugar_expedicion": sucursal.lugar_expedicion,
        "es_matriz": sucursal.es_matriz,
        "activo": sucursal.activo,
        "creado_en": sucursal.creado_en,
        "inventario_resumen": {
            "total_productos": inv_stats.total_productos if inv_stats else 0,
            "total_stock": float(inv_stats.total_stock) if inv_stats else 0,
            "productos_bajo_minimo": bajo_minimo or 0,
        },
    }


def actualizar_sucursal(db: Session, id: int, data: dict) -> Sucursal:
    sucursal = db.query(Sucursal).filter(Sucursal.id == id).first()
    if not sucursal:
        raise ValueError("Sucursal no encontrada")
    for key, value in data.items():
        setattr(sucursal, key, value)
    db.commit()
    db.refresh(sucursal)
    return sucursal


# --- Inventario por sucursal ---

def inicializar_inventario_sucursal(db: Session, sucursal_id: int) -> list[InventarioSucursal]:
    """Crea registros de InventarioSucursal para todos los productos activos con stock=0."""
    sucursal = db.query(Sucursal).filter(Sucursal.id == sucursal_id).first()
    if not sucursal:
        raise ValueError("Sucursal no encontrada")

    productos_activos = db.query(Producto).filter(Producto.activo.is_(True)).all()

    # IDs de productos que ya tienen registro en esta sucursal
    existentes = set(
        row[0] for row in db.query(InventarioSucursal.producto_id).filter(
            InventarioSucursal.sucursal_id == sucursal_id
        ).all()
    )

    nuevos = []
    for producto in productos_activos:
        if producto.id not in existentes:
            inv = InventarioSucursal(
                sucursal_id=sucursal_id,
                producto_id=producto.id,
                stock_actual=Decimal("0"),
                stock_minimo=Decimal("0"),
            )
            db.add(inv)
            nuevos.append(inv)

    db.commit()
    for inv in nuevos:
        db.refresh(inv)
    return nuevos


def obtener_inventario_sucursal(db: Session, sucursal_id: int) -> list[dict]:
    """Obtiene inventario de una sucursal con datos del producto."""
    sucursal = db.query(Sucursal).filter(Sucursal.id == sucursal_id).first()
    if not sucursal:
        raise ValueError("Sucursal no encontrada")

    registros = (
        db.query(InventarioSucursal, Producto)
        .join(Producto, InventarioSucursal.producto_id == Producto.id)
        .filter(InventarioSucursal.sucursal_id == sucursal_id)
        .order_by(Producto.nombre)
        .all()
    )

    resultado = []
    for inv, prod in registros:
        resultado.append({
            "id": inv.id,
            "sucursal_id": inv.sucursal_id,
            "producto_id": inv.producto_id,
            "producto_nombre": prod.nombre,
            "producto_codigo": prod.codigo,
            "precio_unitario": float(prod.precio_unitario),
            "stock_actual": float(inv.stock_actual),
            "stock_minimo": float(inv.stock_minimo),
            "bajo_minimo": inv.stock_actual < inv.stock_minimo,
        })
    return resultado


def actualizar_stock_sucursal(
    db: Session,
    sucursal_id: int,
    producto_id: int,
    cantidad: Decimal,
    operacion: str,
) -> InventarioSucursal:
    """Ajusta stock de un producto en una sucursal. operacion: 'sumar' o 'restar'."""
    inv = db.query(InventarioSucursal).filter(
        and_(
            InventarioSucursal.sucursal_id == sucursal_id,
            InventarioSucursal.producto_id == producto_id,
        )
    ).first()
    if not inv:
        raise ValueError("Registro de inventario no encontrado para esta sucursal/producto")

    if operacion == "sumar":
        inv.stock_actual += cantidad
    elif operacion == "restar":
        if inv.stock_actual < cantidad:
            raise ValueError("Stock insuficiente en la sucursal")
        inv.stock_actual -= cantidad
    else:
        raise ValueError("Operación debe ser 'sumar' o 'restar'")

    db.commit()
    db.refresh(inv)
    return inv


# --- Traspasos ---

def _generar_folio_traspaso(db: Session) -> str:
    """Genera folio con formato TR-YYYYMMDD-NNN."""
    hoy = date.today().strftime("%Y%m%d")
    prefijo = f"TR-{hoy}-"

    ultimo = (
        db.query(Traspaso)
        .filter(Traspaso.folio.like(f"{prefijo}%"))
        .order_by(Traspaso.folio.desc())
        .first()
    )

    if ultimo:
        try:
            ultimo_num = int(ultimo.folio.split("-")[-1])
        except (ValueError, IndexError):
            ultimo_num = 0
        siguiente = ultimo_num + 1
    else:
        siguiente = 1

    return f"{prefijo}{siguiente:03d}"


def crear_traspaso(db: Session, data: dict) -> Traspaso:
    """Crea un traspaso entre sucursales con estado SOLICITADO."""
    origen = db.query(Sucursal).filter(Sucursal.id == data["sucursal_origen_id"]).first()
    if not origen:
        raise ValueError("Sucursal de origen no encontrada")

    destino = db.query(Sucursal).filter(Sucursal.id == data["sucursal_destino_id"]).first()
    if not destino:
        raise ValueError("Sucursal de destino no encontrada")

    if data["sucursal_origen_id"] == data["sucursal_destino_id"]:
        raise ValueError("La sucursal de origen y destino no pueden ser la misma")

    folio = _generar_folio_traspaso(db)

    traspaso = Traspaso(
        folio=folio,
        sucursal_origen_id=data["sucursal_origen_id"],
        sucursal_destino_id=data["sucursal_destino_id"],
        estado=EstadoTraspaso.SOLICITADO,
        notas=data.get("notas"),
        usuario_id=data.get("usuario_id"),
    )
    db.add(traspaso)
    db.flush()  # Get traspaso.id before adding detalles

    for item in data.get("detalles", []):
        detalle = DetalleTraspaso(
            traspaso_id=traspaso.id,
            producto_id=item["producto_id"],
            cantidad_enviada=Decimal(str(item["cantidad_enviada"])),
            cantidad_recibida=Decimal("0"),
        )
        db.add(detalle)

    db.commit()
    db.refresh(traspaso)
    return traspaso


def listar_traspasos(
    db: Session,
    sucursal_id: int | None = None,
    estado: str | None = None,
) -> list[Traspaso]:
    query = db.query(Traspaso).options(
        joinedload(Traspaso.sucursal_origen),
        joinedload(Traspaso.sucursal_destino),
        joinedload(Traspaso.detalles),
    )

    if sucursal_id is not None:
        query = query.filter(
            (Traspaso.sucursal_origen_id == sucursal_id)
            | (Traspaso.sucursal_destino_id == sucursal_id)
        )
    if estado is not None:
        query = query.filter(Traspaso.estado == estado)

    return query.order_by(Traspaso.creado_en.desc()).all()


def enviar_traspaso(db: Session, traspaso_id: int) -> Traspaso:
    """Cambia a EN_TRANSITO y descuenta stock de la sucursal origen."""
    traspaso = db.query(Traspaso).options(
        joinedload(Traspaso.detalles),
    ).filter(Traspaso.id == traspaso_id).first()
    if not traspaso:
        raise ValueError("Traspaso no encontrado")
    if traspaso.estado != EstadoTraspaso.SOLICITADO:
        raise ValueError("Solo se puede enviar un traspaso en estado SOLICITADO")

    # Descontar stock del origen
    for detalle in traspaso.detalles:
        inv = db.query(InventarioSucursal).filter(
            and_(
                InventarioSucursal.sucursal_id == traspaso.sucursal_origen_id,
                InventarioSucursal.producto_id == detalle.producto_id,
            )
        ).first()
        if not inv:
            raise ValueError(
                f"No hay registro de inventario para producto {detalle.producto_id} "
                f"en sucursal origen {traspaso.sucursal_origen_id}"
            )
        if inv.stock_actual < detalle.cantidad_enviada:
            raise ValueError(
                f"Stock insuficiente del producto {detalle.producto_id} en sucursal origen. "
                f"Disponible: {inv.stock_actual}, requerido: {detalle.cantidad_enviada}"
            )
        inv.stock_actual -= detalle.cantidad_enviada

    traspaso.estado = EstadoTraspaso.EN_TRANSITO
    db.commit()
    db.refresh(traspaso)
    return traspaso


def recibir_traspaso(
    db: Session,
    traspaso_id: int,
    items_recibidos: list[dict],
) -> Traspaso:
    """Marca como RECIBIDO, agrega stock a destino, actualiza cantidad_recibida."""
    traspaso = db.query(Traspaso).options(
        joinedload(Traspaso.detalles),
    ).filter(Traspaso.id == traspaso_id).first()
    if not traspaso:
        raise ValueError("Traspaso no encontrado")
    if traspaso.estado != EstadoTraspaso.EN_TRANSITO:
        raise ValueError("Solo se puede recibir un traspaso EN_TRANSITO")

    # Map recibidos by producto_id
    recibidos_map = {item["producto_id"]: Decimal(str(item["cantidad_recibida"])) for item in items_recibidos}

    for detalle in traspaso.detalles:
        cantidad_recibida = recibidos_map.get(detalle.producto_id, detalle.cantidad_enviada)
        detalle.cantidad_recibida = cantidad_recibida

        # Agregar stock al destino
        inv = db.query(InventarioSucursal).filter(
            and_(
                InventarioSucursal.sucursal_id == traspaso.sucursal_destino_id,
                InventarioSucursal.producto_id == detalle.producto_id,
            )
        ).first()
        if not inv:
            # Auto-create inventory record at destination
            inv = InventarioSucursal(
                sucursal_id=traspaso.sucursal_destino_id,
                producto_id=detalle.producto_id,
                stock_actual=Decimal("0"),
                stock_minimo=Decimal("0"),
            )
            db.add(inv)
            db.flush()
        inv.stock_actual += cantidad_recibida

    traspaso.estado = EstadoTraspaso.RECIBIDO
    traspaso.recibido_en = datetime.now(timezone.utc)
    db.commit()
    db.refresh(traspaso)
    return traspaso


def cancelar_traspaso(db: Session, traspaso_id: int) -> Traspaso:
    """Cancela un traspaso. Restaura stock en origen si estaba EN_TRANSITO."""
    traspaso = db.query(Traspaso).options(
        joinedload(Traspaso.detalles),
    ).filter(Traspaso.id == traspaso_id).first()
    if not traspaso:
        raise ValueError("Traspaso no encontrado")
    if traspaso.estado not in (EstadoTraspaso.SOLICITADO, EstadoTraspaso.EN_TRANSITO):
        raise ValueError("Solo se puede cancelar un traspaso SOLICITADO o EN_TRANSITO")

    # Si estaba en tránsito, restaurar stock en origen
    if traspaso.estado == EstadoTraspaso.EN_TRANSITO:
        for detalle in traspaso.detalles:
            inv = db.query(InventarioSucursal).filter(
                and_(
                    InventarioSucursal.sucursal_id == traspaso.sucursal_origen_id,
                    InventarioSucursal.producto_id == detalle.producto_id,
                )
            ).first()
            if inv:
                inv.stock_actual += detalle.cantidad_enviada

    traspaso.estado = EstadoTraspaso.CANCELADO
    db.commit()
    db.refresh(traspaso)
    return traspaso


# --- Reportes ---

def reporte_comparativo(db: Session) -> list[dict]:
    """Comparativo de inventario entre sucursales."""
    sucursales = db.query(Sucursal).filter(Sucursal.activo.is_(True)).all()
    resultado = []

    for sucursal in sucursales:
        inventario = (
            db.query(InventarioSucursal, Producto)
            .join(Producto, InventarioSucursal.producto_id == Producto.id)
            .filter(InventarioSucursal.sucursal_id == sucursal.id)
            .all()
        )

        total_valor = Decimal("0")
        bajo_minimo = []
        for inv, prod in inventario:
            total_valor += inv.stock_actual * prod.precio_unitario
            if inv.stock_actual < inv.stock_minimo:
                bajo_minimo.append({
                    "producto_id": prod.id,
                    "producto_nombre": prod.nombre,
                    "stock_actual": float(inv.stock_actual),
                    "stock_minimo": float(inv.stock_minimo),
                })

        resultado.append({
            "sucursal_id": sucursal.id,
            "sucursal_nombre": sucursal.nombre,
            "sucursal_codigo": sucursal.codigo,
            "es_matriz": sucursal.es_matriz,
            "total_productos": len(inventario),
            "valor_total_stock": float(total_valor),
            "productos_bajo_minimo": bajo_minimo,
            "cantidad_bajo_minimo": len(bajo_minimo),
        })

    return resultado


def dashboard_sucursales(db: Session) -> dict:
    """Dashboard general multi-sucursal."""
    sucursales = db.query(Sucursal).filter(Sucursal.activo.is_(True)).all()
    total_sucursales = len(sucursales)

    resumen_por_sucursal = []
    for sucursal in sucursales:
        valor_stock = db.query(
            func.coalesce(
                func.sum(InventarioSucursal.stock_actual * Producto.precio_unitario),
                Decimal("0"),
            )
        ).join(
            Producto, InventarioSucursal.producto_id == Producto.id
        ).filter(
            InventarioSucursal.sucursal_id == sucursal.id
        ).scalar()

        resumen_por_sucursal.append({
            "sucursal_id": sucursal.id,
            "nombre": sucursal.nombre,
            "codigo": sucursal.codigo,
            "es_matriz": sucursal.es_matriz,
            "valor_total_stock": float(valor_stock or 0),
        })

    # Traspasos pendientes (SOLICITADO + EN_TRANSITO)
    traspasos_pendientes = db.query(func.count(Traspaso.id)).filter(
        Traspaso.estado.in_([EstadoTraspaso.SOLICITADO, EstadoTraspaso.EN_TRANSITO])
    ).scalar()

    traspasos_solicitados = db.query(func.count(Traspaso.id)).filter(
        Traspaso.estado == EstadoTraspaso.SOLICITADO
    ).scalar()

    traspasos_en_transito = db.query(func.count(Traspaso.id)).filter(
        Traspaso.estado == EstadoTraspaso.EN_TRANSITO
    ).scalar()

    return {
        "total_sucursales": total_sucursales,
        "sucursales": resumen_por_sucursal,
        "traspasos_pendientes": traspasos_pendientes or 0,
        "traspasos_solicitados": traspasos_solicitados or 0,
        "traspasos_en_transito": traspasos_en_transito or 0,
    }
