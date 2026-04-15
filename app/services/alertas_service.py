"""
Servicio de alertas automáticas del sistema.
Consolida alertas de stock, caducidades, pedidos y mermas.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.inventario import (
    Ingrediente, Producto, LoteIngrediente,
    MovimientoInventario, TipoMovimiento,
)
from app.models.pedido import Pedido, EstadoPedido
from app.models.venta import Venta, EstadoVenta


def alertas_consolidadas(db: Session) -> dict:
    """Genera todas las alertas activas del sistema."""
    return {
        "stock_bajo": _alertas_stock_bajo(db),
        "caducidades": _alertas_caducidades(db),
        "pedidos_pendientes": _alertas_pedidos(db),
        "merma_hoy": _alertas_merma(db),
        "resumen": {},  # Se calcula al final
    }


def _alertas_stock_bajo(db: Session) -> list[dict]:
    """Ingredientes y productos con stock por debajo del mínimo."""
    alertas = []

    # Ingredientes con stock bajo
    ingredientes = db.query(Ingrediente).filter(
        and_(
            Ingrediente.stock_actual <= Ingrediente.stock_minimo,
            Ingrediente.stock_minimo > 0,
        )
    ).all()
    for ing in ingredientes:
        porcentaje = (
            float(ing.stock_actual / ing.stock_minimo * 100)
            if ing.stock_minimo > 0 else 0
        )
        alertas.append({
            "tipo": "ingrediente",
            "id": ing.id,
            "nombre": ing.nombre,
            "stock_actual": float(ing.stock_actual),
            "stock_minimo": float(ing.stock_minimo),
            "unidad": ing.unidad_medida.value if ing.unidad_medida else "",
            "porcentaje": round(porcentaje, 1),
            "severidad": "critica" if ing.stock_actual <= 0 else "alta",
        })

    # Productos con stock bajo
    productos = db.query(Producto).filter(
        and_(
            Producto.activo.is_(True),
            Producto.stock_actual <= Producto.stock_minimo,
            Producto.stock_minimo > 0,
        )
    ).all()
    for prod in productos:
        porcentaje = (
            float(prod.stock_actual / prod.stock_minimo * 100)
            if prod.stock_minimo > 0 else 0
        )
        alertas.append({
            "tipo": "producto",
            "id": prod.id,
            "nombre": prod.nombre,
            "stock_actual": float(prod.stock_actual),
            "stock_minimo": float(prod.stock_minimo),
            "unidad": prod.unidad_medida.value if prod.unidad_medida else "",
            "porcentaje": round(porcentaje, 1),
            "severidad": "critica" if prod.stock_actual <= 0 else "alta",
        })

    return sorted(alertas, key=lambda a: a["porcentaje"])


def _alertas_caducidades(db: Session, dias_aviso: int = 3) -> list[dict]:
    """Lotes de ingredientes próximos a caducar o ya caducados."""
    hoy = date.today()
    limite = hoy + timedelta(days=dias_aviso)

    lotes = db.query(LoteIngrediente).filter(
        and_(
            LoteIngrediente.fecha_caducidad.isnot(None),
            LoteIngrediente.fecha_caducidad <= limite,
            LoteIngrediente.cantidad_disponible > 0,
        )
    ).all()

    alertas = []
    for lote in lotes:
        ing = db.query(Ingrediente).filter(
            Ingrediente.id == lote.ingrediente_id
        ).first()
        dias_restantes = (lote.fecha_caducidad - hoy).days
        alertas.append({
            "ingrediente": ing.nombre if ing else f"ID {lote.ingrediente_id}",
            "lote": lote.numero_lote,
            "cantidad_disponible": float(lote.cantidad_disponible),
            "fecha_caducidad": lote.fecha_caducidad.isoformat(),
            "dias_restantes": dias_restantes,
            "severidad": "critica" if dias_restantes <= 0 else (
                "alta" if dias_restantes <= 1 else "media"
            ),
        })

    return sorted(alertas, key=lambda a: a["dias_restantes"])


def _alertas_pedidos(db: Session) -> list[dict]:
    """Pedidos pendientes: sin confirmar o con entrega próxima."""
    hoy = date.today()
    manana = hoy + timedelta(days=1)

    # Pedidos sin confirmar (recibidos hace > 2 horas)
    hace_2h = datetime.now(timezone.utc) - timedelta(hours=2)
    pedidos = db.query(Pedido).filter(
        Pedido.estado.in_([
            EstadoPedido.RECIBIDO,
            EstadoPedido.CONFIRMADO,
            EstadoPedido.EN_PREPARACION,
        ]),
    ).all()

    alertas = []
    for p in pedidos:
        dias_para_entrega = (p.fecha_entrega - hoy).days
        # Determinar severidad
        if p.estado == EstadoPedido.RECIBIDO:
            if p.creado_en and p.creado_en.replace(tzinfo=timezone.utc) < hace_2h:
                severidad = "alta"
                razon = "Sin confirmar por más de 2 horas"
            else:
                severidad = "media"
                razon = "Pendiente de confirmación"
        elif dias_para_entrega <= 0:
            severidad = "critica"
            razon = "Entrega hoy" if dias_para_entrega == 0 else "Entrega atrasada"
        elif dias_para_entrega == 1:
            severidad = "alta"
            razon = "Entrega mañana"
        else:
            severidad = "baja"
            razon = f"Entrega en {dias_para_entrega} días"

        alertas.append({
            "pedido_id": p.id,
            "cliente": p.cliente_nombre,
            "estado": p.estado.value,
            "fecha_entrega": p.fecha_entrega.isoformat(),
            "dias_para_entrega": dias_para_entrega,
            "razon": razon,
            "severidad": severidad,
        })

    return sorted(alertas, key=lambda a: a["dias_para_entrega"])


def _alertas_merma(db: Session) -> dict:
    """Merma del día actual."""
    hoy_inicio = datetime.combine(date.today(), datetime.min.time())
    hoy_fin = datetime.combine(date.today(), datetime.max.time())

    mermas = db.query(MovimientoInventario).filter(
        and_(
            MovimientoInventario.tipo.in_([
                TipoMovimiento.SALIDA_MERMA,
                TipoMovimiento.SALIDA_CADUCIDAD,
            ]),
            MovimientoInventario.fecha >= hoy_inicio,
            MovimientoInventario.fecha <= hoy_fin,
        )
    ).all()

    total_unidades = sum(float(m.cantidad) for m in mermas)

    # Comparar con producción del día
    produccion = db.query(
        func.sum(MovimientoInventario.cantidad)
    ).filter(
        and_(
            MovimientoInventario.tipo == TipoMovimiento.ENTRADA_PRODUCCION,
            MovimientoInventario.fecha >= hoy_inicio,
            MovimientoInventario.fecha <= hoy_fin,
        )
    ).scalar() or Decimal("0")

    porcentaje_merma = (
        round(total_unidades / float(produccion) * 100, 1)
        if produccion > 0 else 0
    )

    return {
        "total_movimientos": len(mermas),
        "total_unidades": round(total_unidades, 2),
        "produccion_dia": float(produccion),
        "porcentaje_merma": porcentaje_merma,
        "severidad": "alta" if porcentaje_merma > 5 else (
            "media" if porcentaje_merma > 2 else "baja"
        ),
    }
