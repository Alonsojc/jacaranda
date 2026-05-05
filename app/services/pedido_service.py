"""Servicio de gestión de pedidos."""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from app.core.config import settings
from app.models.inventario import Producto
from app.models.pedido import Pedido, DetallePedido, EstadoPedido, OrigenPedido
from app.schemas.pedido import PedidoCreate, PedidoUpdate
from app.services.auditoria_service import registrar_evento


_TRANSICIONES_ESTADO: dict[EstadoPedido, set[EstadoPedido]] = {
    EstadoPedido.RECIBIDO: {EstadoPedido.CONFIRMADO, EstadoPedido.CANCELADO},
    EstadoPedido.CONFIRMADO: {EstadoPedido.EN_PREPARACION, EstadoPedido.CANCELADO},
    EstadoPedido.EN_PREPARACION: {EstadoPedido.LISTO, EstadoPedido.CANCELADO},
    EstadoPedido.LISTO: {
        EstadoPedido.EN_RUTA,
        EstadoPedido.ENTREGADO,
        EstadoPedido.CANCELADO,
    },
    EstadoPedido.EN_RUTA: {EstadoPedido.ENTREGADO, EstadoPedido.CANCELADO},
    EstadoPedido.ENTREGADO: set(),
    EstadoPedido.CANCELADO: set(),
}

_ESTADOS_QUE_RESERVAN = (
    EstadoPedido.RECIBIDO,
    EstadoPedido.CONFIRMADO,
    EstadoPedido.EN_PREPARACION,
    EstadoPedido.LISTO,
    EstadoPedido.EN_RUTA,
)


def _capacidad_diaria() -> int:
    value = getattr(settings, "PEDIDOS_CAPACIDAD_DIARIA", 0)
    if isinstance(value, int):
        return max(value, 0)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _generar_folio_pedido(db: Session) -> str:
    ultimo = db.query(Pedido).order_by(Pedido.id.desc()).with_for_update().first()
    numero = (int(ultimo.folio.replace("P-", "")) + 1) if ultimo else 1
    return f"P-{numero:05d}"


def stock_reservado_producto(
    db: Session,
    producto_id: int,
    exclude_pedido_id: int | None = None,
) -> int:
    """Cantidad comprometida en pedidos activos."""
    query = (
        db.query(func.coalesce(func.sum(DetallePedido.cantidad), 0))
        .join(Pedido, Pedido.id == DetallePedido.pedido_id)
        .filter(
            DetallePedido.producto_id == producto_id,
            Pedido.estado.in_(_ESTADOS_QUE_RESERVAN),
            Pedido.fecha_entrega >= date.today(),
        )
    )
    if exclude_pedido_id:
        query = query.filter(Pedido.id != exclude_pedido_id)
    return int(query.scalar() or 0)


def _validar_capacidad_diaria(db: Session, fecha_entrega: date) -> None:
    capacidad = _capacidad_diaria()
    if capacidad <= 0:
        return
    activos = db.query(func.count(Pedido.id)).filter(
        Pedido.fecha_entrega == fecha_entrega,
        Pedido.estado.in_(_ESTADOS_QUE_RESERVAN),
    ).scalar() or 0
    if activos >= capacidad:
        raise ValueError(
            f"Capacidad diaria llena para {fecha_entrega.isoformat()} "
            f"({activos}/{capacidad} pedidos activos)"
        )


def _validar_stock_reservado(db: Session, data: PedidoCreate) -> None:
    cantidades: dict[int, int] = {}
    for detalle in data.detalles:
        if detalle.producto_id:
            cantidades[detalle.producto_id] = (
                cantidades.get(detalle.producto_id, 0) + detalle.cantidad
            )

    for producto_id, cantidad in cantidades.items():
        producto = (
            db.query(Producto)
            .filter(Producto.id == producto_id)
            .with_for_update()
            .first()
        )
        if not producto or not producto.activo:
            raise ValueError(f"Producto {producto_id} no encontrado o inactivo")

        reservado = Decimal(stock_reservado_producto(db, producto_id))
        disponible = Decimal(producto.stock_actual or 0) - reservado
        if Decimal(cantidad) > disponible:
            raise ValueError(
                f"Stock reservado insuficiente para {producto.nombre}: "
                f"disponible {max(disponible, Decimal('0'))}, pedido {cantidad}"
            )


def crear_pedido(db: Session, data: PedidoCreate) -> Pedido:
    if data.idempotency_key:
        pedido_existente = db.query(Pedido).filter(
            Pedido.idempotency_key == data.idempotency_key
        ).first()
        if pedido_existente:
            return pedido_existente

    _validar_capacidad_diaria(db, data.fecha_entrega)
    _validar_stock_reservado(db, data)

    total = sum(d.precio_unitario * d.cantidad for d in data.detalles)

    for _attempt in range(3):
        folio = _generar_folio_pedido(db)

        pedido = Pedido(
            folio=folio,
            idempotency_key=data.idempotency_key,
            cliente_nombre=data.cliente_nombre,
            cliente_telefono=data.cliente_telefono,
            cliente_id=data.cliente_id,
            fecha_entrega=data.fecha_entrega,
            hora_entrega=data.hora_entrega,
            lugar_entrega=data.lugar_entrega,
            estado=EstadoPedido.RECIBIDO,
            origen=OrigenPedido(data.origen) if data.origen else OrigenPedido.WHATSAPP,
            anticipo=data.anticipo,
            total=total if total > 0 else data.anticipo,
            notas=data.notas,
            notas_internas=data.notas_internas,
        )
        db.add(pedido)
        try:
            db.flush()

            for d in data.detalles:
                detalle = DetallePedido(
                    pedido_id=pedido.id,
                    producto_id=d.producto_id,
                    descripcion=d.descripcion,
                    cantidad=d.cantidad,
                    precio_unitario=d.precio_unitario,
                    notas=d.notas,
                )
                db.add(detalle)

            db.commit()
            db.refresh(pedido)
            return pedido
        except IntegrityError:
            db.rollback()
            if data.idempotency_key:
                pedido_existente = db.query(Pedido).filter(
                    Pedido.idempotency_key == data.idempotency_key
                ).first()
                if pedido_existente:
                    return pedido_existente

    raise ValueError("No se pudo generar un folio único, intente de nuevo")


def actualizar_pedido(
    db: Session, pedido_id: int, data: PedidoUpdate, usuario_id: int | None = None
) -> Pedido:
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise ValueError("Pedido no encontrado")

    updates = data.model_dump(exclude_none=True)
    if "pagado" in updates:
        raise ValueError("No se puede marcar pagado desde edición general; use el flujo de pago")

    if "estado" in updates:
        estado = updates.pop("estado")
        pedido = cambiar_estado_pedido(db, pedido_id, estado, usuario_id, commit=False)

    datos_anteriores = {field: getattr(pedido, field, None) for field in updates}

    for field, value in updates.items():
        setattr(pedido, field, value)

    if updates:
        registrar_evento(
            db,
            usuario_id=usuario_id,
            usuario_nombre=None,
            accion="actualizar",
            modulo="pedidos",
            entidad="pedidos",
            entidad_id=pedido.id,
            datos_anteriores=datos_anteriores,
            datos_nuevos={field: getattr(pedido, field, None) for field in updates},
            commit=False,
        )

    db.commit()
    db.refresh(pedido)
    return pedido


def cambiar_estado_pedido(
    db: Session,
    pedido_id: int,
    nuevo_estado: str,
    usuario_id: int | None = None,
    commit: bool = True,
) -> Pedido:
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).with_for_update().first()
    if not pedido:
        raise ValueError("Pedido no encontrado")

    try:
        estado_destino = EstadoPedido(nuevo_estado)
    except ValueError as exc:
        raise ValueError("Estado de pedido inválido") from exc

    estado_anterior = pedido.estado
    if estado_destino == estado_anterior:
        return pedido
    permitidas = _TRANSICIONES_ESTADO.get(estado_anterior, set())
    if estado_destino not in permitidas:
        raise ValueError(
            f"Transición inválida de '{estado_anterior.value}' a '{estado_destino.value}'"
        )

    pedido.estado = estado_destino
    ahora = datetime.now(timezone.utc)
    if estado_destino == EstadoPedido.EN_RUTA:
        pedido.en_ruta_en = ahora
    elif estado_destino == EstadoPedido.ENTREGADO:
        pedido.entregado_en = ahora

    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="cambiar_estado",
        modulo="pedidos",
        entidad="pedidos",
        entidad_id=pedido.id,
        datos_anteriores={"estado": estado_anterior.value},
        datos_nuevos={"estado": estado_destino.value},
        commit=False,
    )
    if commit:
        db.commit()
        db.refresh(pedido)
    return pedido


def marcar_pago_manual(
    db: Session,
    pedido_id: int,
    pagado: bool,
    usuario_id: int | None = None,
    motivo: str | None = None,
) -> Pedido:
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).with_for_update().first()
    if not pedido:
        raise ValueError("Pedido no encontrado")
    if pedido.estado == EstadoPedido.CANCELADO:
        raise ValueError("No se puede cambiar pago de un pedido cancelado")
    if pedido.pagado == pagado:
        return pedido

    pagado_anterior = pedido.pagado
    pedido.pagado = pagado
    registrar_evento(
        db,
        usuario_id=usuario_id,
        usuario_nombre=None,
        accion="marcar_pago",
        modulo="pedidos",
        entidad="pedidos",
        entidad_id=pedido.id,
        datos_anteriores={"pagado": pagado_anterior},
        datos_nuevos={"pagado": pagado, "motivo": motivo},
        commit=False,
    )
    db.commit()
    db.refresh(pedido)
    return pedido


def listar_pedidos(
    db: Session,
    fecha: date | None = None,
    estado: str | None = None,
    limit: int = 50,
) -> list[Pedido]:
    query = db.query(Pedido)
    if fecha:
        query = query.filter(Pedido.fecha_entrega == fecha)
    if estado:
        query = query.filter(Pedido.estado == EstadoPedido(estado))
    return query.order_by(Pedido.fecha_entrega.asc()).limit(limit).all()


def pedidos_del_dia(db: Session, fecha: date | None = None) -> list[Pedido]:
    if not fecha:
        fecha = date.today()
    return (
        db.query(Pedido)
        .filter(Pedido.fecha_entrega == fecha)
        .filter(Pedido.estado != EstadoPedido.CANCELADO)
        .order_by(Pedido.hora_entrega.asc())
        .all()
    )


def obtener_pedido(db: Session, pedido_id: int) -> Pedido:
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise ValueError("Pedido no encontrado")
    return pedido


def resumen_reservas(db: Session, fecha: date | None = None) -> dict:
    """Resumen de stock/capacidad comprometidos por pedidos activos."""
    dia = fecha or date.today()
    capacidad = _capacidad_diaria()
    activos = db.query(Pedido).filter(
        Pedido.fecha_entrega == dia,
        Pedido.estado.in_(_ESTADOS_QUE_RESERVAN),
    ).all()
    reservas = (
        db.query(
            DetallePedido.producto_id,
            Producto.nombre,
            Producto.stock_actual,
            func.sum(DetallePedido.cantidad).label("reservado"),
        )
        .join(Pedido, Pedido.id == DetallePedido.pedido_id)
        .join(Producto, Producto.id == DetallePedido.producto_id)
        .filter(
            Pedido.estado.in_(_ESTADOS_QUE_RESERVAN),
            Pedido.fecha_entrega >= date.today(),
            DetallePedido.producto_id.isnot(None),
        )
        .group_by(DetallePedido.producto_id, Producto.nombre, Producto.stock_actual)
        .all()
    )
    return {
        "fecha": dia.isoformat(),
        "capacidad_diaria": capacidad,
        "pedidos_activos_dia": len(activos),
        "capacidad_disponible": None if capacidad <= 0 else max(capacidad - len(activos), 0),
        "productos": [
            {
                "producto_id": r.producto_id,
                "nombre": r.nombre,
                "stock_actual": float(r.stock_actual or 0),
                "reservado": int(r.reservado or 0),
                "disponible": float(Decimal(r.stock_actual or 0) - Decimal(r.reservado or 0)),
            }
            for r in reservas
        ],
    }
