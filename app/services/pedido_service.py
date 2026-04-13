"""Servicio de gestión de pedidos."""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session

from app.models.pedido import Pedido, DetallePedido, EstadoPedido, OrigenPedido
from app.schemas.pedido import PedidoCreate, PedidoUpdate


def _generar_folio_pedido(db: Session) -> str:
    ultimo = db.query(Pedido).order_by(Pedido.id.desc()).first()
    numero = (int(ultimo.folio.replace("P-", "")) + 1) if ultimo else 1
    return f"P-{numero:05d}"


def crear_pedido(db: Session, data: PedidoCreate) -> Pedido:
    folio = _generar_folio_pedido(db)
    total = sum(d.precio_unitario * d.cantidad for d in data.detalles)

    pedido = Pedido(
        folio=folio,
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


def actualizar_pedido(db: Session, pedido_id: int, data: PedidoUpdate) -> Pedido:
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise ValueError("Pedido no encontrado")

    for field, value in data.model_dump(exclude_none=True).items():
        if field == "estado":
            setattr(pedido, field, EstadoPedido(value))
        else:
            setattr(pedido, field, value)

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
