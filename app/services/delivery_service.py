"""Servicio de tracking de entregas."""

from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.db_compat import db_cast_date
from app.models.pedido import Pedido, EstadoPedido


def marcar_en_ruta(
    db: Session,
    pedido_id: int,
    repartidor_nombre: str,
    repartidor_telefono: str | None = None,
) -> Pedido:
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise ValueError("Pedido no encontrado")
    if pedido.estado != EstadoPedido.LISTO:
        raise ValueError("Solo pedidos en estado 'listo' pueden salir a ruta")
    pedido.estado = EstadoPedido.EN_RUTA
    pedido.en_ruta_en = datetime.now(timezone.utc)
    pedido.repartidor_nombre = repartidor_nombre
    pedido.repartidor_telefono = repartidor_telefono
    db.commit()
    db.refresh(pedido)
    return pedido


def marcar_entregado(db: Session, pedido_id: int) -> Pedido:
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise ValueError("Pedido no encontrado")
    if pedido.estado != EstadoPedido.EN_RUTA:
        raise ValueError("Solo pedidos en ruta pueden marcarse como entregados")
    pedido.estado = EstadoPedido.ENTREGADO
    pedido.entregado_en = datetime.now(timezone.utc)
    db.commit()
    db.refresh(pedido)
    return pedido


def pedidos_en_ruta(db: Session) -> list[Pedido]:
    return (
        db.query(Pedido)
        .filter(Pedido.estado == EstadoPedido.EN_RUTA)
        .order_by(Pedido.en_ruta_en.asc())
        .all()
    )


def tracking_pedido(db: Session, folio: str) -> dict:
    pedido = db.query(Pedido).filter(Pedido.folio == folio).first()
    if not pedido:
        raise ValueError("Pedido no encontrado")
    return {
        "folio": pedido.folio,
        "estado": pedido.estado.value,
        "cliente_nombre": pedido.cliente_nombre,
        "fecha_entrega": pedido.fecha_entrega,
        "hora_entrega": pedido.hora_entrega,
        "lugar_entrega": pedido.lugar_entrega,
        "repartidor_nombre": pedido.repartidor_nombre,
        "repartidor_telefono": pedido.repartidor_telefono,
        "en_ruta_en": pedido.en_ruta_en,
        "entregado_en": pedido.entregado_en,
    }


def dashboard_delivery(db: Session) -> dict:
    hoy = date.today()

    en_ruta = (
        db.query(func.count(Pedido.id))
        .filter(Pedido.estado == EstadoPedido.EN_RUTA)
        .scalar()
    )

    listos_para_envio = (
        db.query(func.count(Pedido.id))
        .filter(Pedido.estado == EstadoPedido.LISTO)
        .scalar()
    )

    entregados_hoy = (
        db.query(func.count(Pedido.id))
        .filter(Pedido.estado == EstadoPedido.ENTREGADO)
        .filter(db_cast_date(Pedido.entregado_en) == hoy)
        .scalar()
    )

    # Tiempo promedio de entrega (en_ruta_en -> entregado_en) para hoy
    entregas_hoy = (
        db.query(Pedido)
        .filter(Pedido.estado == EstadoPedido.ENTREGADO)
        .filter(db_cast_date(Pedido.entregado_en) == hoy)
        .filter(Pedido.en_ruta_en.isnot(None))
        .filter(Pedido.entregado_en.isnot(None))
        .all()
    )

    tiempo_promedio = 0.0
    if entregas_hoy:
        tiempos = [
            (p.entregado_en - p.en_ruta_en).total_seconds() / 60
            for p in entregas_hoy
        ]
        tiempo_promedio = round(sum(tiempos) / len(tiempos), 1)

    return {
        "en_ruta": en_ruta,
        "listos_para_envio": listos_para_envio,
        "entregados_hoy": entregados_hoy,
        "tiempo_promedio_entrega_min": tiempo_promedio,
    }
