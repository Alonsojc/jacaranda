"""Servicio de gestión de pedidos."""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.pedido import Pedido, DetallePedido, EstadoPedido, OrigenPedido
from app.schemas.pedido import PedidoCreate, PedidoUpdate
from app.services.auditoria_service import registrar_evento


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
    datos_anteriores = {field: getattr(pedido, field, None) for field in updates}

    for field, value in updates.items():
        if field == "estado":
            setattr(pedido, field, EstadoPedido(value))
            if value == "en_ruta":
                pedido.en_ruta_en = datetime.now(timezone.utc)
            elif value == "entregado":
                pedido.entregado_en = datetime.now(timezone.utc)
        else:
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
