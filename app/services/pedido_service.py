"""Servicio de gestión de pedidos."""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

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


def _generar_folio_pedido(db: Session) -> str:
    ultimo = db.query(Pedido).order_by(Pedido.id.desc()).with_for_update().first()
    numero = (int(ultimo.folio.replace("P-", "")) + 1) if ultimo else 1
    return f"P-{numero:05d}"


def crear_pedido(db: Session, data: PedidoCreate) -> Pedido:
    if data.idempotency_key:
        pedido_existente = db.query(Pedido).filter(
            Pedido.idempotency_key == data.idempotency_key
        ).first()
        if pedido_existente:
            return pedido_existente

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
