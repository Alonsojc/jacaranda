"""
Servicio de KPIs consolidados para dashboard con gráficas (Chart.js).
Agrega métricas de todos los módulos del sistema.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.core.db_compat import db_extract_hour, db_extract_dow
from app.models.venta import Venta, DetalleVenta, EstadoVenta
from app.models.inventario import Producto, Ingrediente
from app.models.cliente import Cliente


def _rango_dia(dia: date):
    return (
        datetime.combine(dia, datetime.min.time()),
        datetime.combine(dia, datetime.max.time()),
    )


def _float(v) -> float:
    if v is None:
        return 0.0
    return float(v)


# ─── Ventas por hora (para gráfica de barras) ───────────────────

def ventas_por_hora(db: Session, fecha: date | None = None) -> list[dict]:
    """Ventas agrupadas por hora del día."""
    dia = fecha or date.today()
    inicio, fin = _rango_dia(dia)

    _hour = db_extract_hour(Venta.fecha)
    rows = db.query(
        _hour.label("hora"),
        func.sum(Venta.total).label("total"),
        func.count(Venta.id).label("cantidad"),
    ).filter(
        and_(
            Venta.fecha >= inicio,
            Venta.fecha <= fin,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).group_by(_hour).order_by("hora").all()

    return [
        {"hora": f"{r.hora}:00", "total": _float(r.total), "cantidad": r.cantidad}
        for r in rows
    ]


# ─── Ventas por día de la semana (últimas N semanas) ────────────

def ventas_por_dia_semana(db: Session, semanas: int = 4) -> list[dict]:
    """Promedio de ventas por día de la semana."""
    inicio = datetime.combine(
        date.today() - timedelta(weeks=semanas), datetime.min.time()
    )
    fin = datetime.combine(date.today(), datetime.max.time())

    _dow = db_extract_dow(Venta.fecha)
    rows = db.query(
        _dow.label("dow"),
        func.sum(Venta.total).label("total"),
        func.count(Venta.id).label("cantidad"),
    ).filter(
        and_(
            Venta.fecha >= inicio,
            Venta.fecha <= fin,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).group_by(_dow).all()

    nombres = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"]
    result = []
    for r in rows:
        idx = int(r.dow)
        result.append({
            "dia": nombres[idx],
            "dia_num": idx,
            "total": round(_float(r.total) / semanas, 2),
            "cantidad_promedio": round(r.cantidad / semanas, 1),
        })
    result.sort(key=lambda x: x["dia_num"])
    return result


# ─── Top productos (para gráfica de pie/barras) ────────────────

def top_productos(db: Session, dias: int = 30, limite: int = 10) -> list[dict]:
    """Productos más vendidos por cantidad y monto."""
    inicio = datetime.combine(
        date.today() - timedelta(days=dias - 1), datetime.min.time()
    )
    fin = datetime.combine(date.today(), datetime.max.time())

    rows = db.query(
        DetalleVenta.producto_id,
        func.sum(DetalleVenta.cantidad).label("cantidad"),
        func.sum(DetalleVenta.subtotal).label("total"),
    ).join(Venta).filter(
        and_(
            Venta.fecha >= inicio,
            Venta.fecha <= fin,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).group_by(DetalleVenta.producto_id).order_by(
        func.sum(DetalleVenta.subtotal).desc()
    ).limit(limite).all()

    result = []
    for r in rows:
        prod = db.query(Producto).filter(Producto.id == r.producto_id).first()
        result.append({
            "producto_id": r.producto_id,
            "nombre": prod.nombre if prod else f"Producto #{r.producto_id}",
            "cantidad": int(r.cantidad),
            "total": _float(r.total),
        })
    return result


# ─── Tendencia de ventas diarias (últimos N días) ──────────────

def tendencia_ventas(db: Session, dias: int = 30) -> list[dict]:
    """Ventas diarias para gráfica de línea."""
    result = []
    hoy = date.today()
    for i in range(dias - 1, -1, -1):
        dia = hoy - timedelta(days=i)
        inicio, fin = _rango_dia(dia)

        row = db.query(
            func.sum(Venta.total).label("total"),
            func.count(Venta.id).label("cantidad"),
        ).filter(
            and_(
                Venta.fecha >= inicio,
                Venta.fecha <= fin,
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        ).first()

        result.append({
            "fecha": dia.isoformat(),
            "total": _float(row.total) if row else 0,
            "cantidad": row.cantidad if row else 0,
        })
    return result


# ─── Ticket promedio por día ─────────────────────────────────────

def ticket_promedio_diario(db: Session, dias: int = 30) -> list[dict]:
    """Ticket promedio diario para gráfica de línea."""
    result = []
    hoy = date.today()
    for i in range(dias - 1, -1, -1):
        dia = hoy - timedelta(days=i)
        inicio, fin = _rango_dia(dia)

        row = db.query(
            func.avg(Venta.total).label("promedio"),
            func.count(Venta.id).label("cantidad"),
        ).filter(
            and_(
                Venta.fecha >= inicio,
                Venta.fecha <= fin,
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        ).first()

        result.append({
            "fecha": dia.isoformat(),
            "ticket_promedio": round(_float(row.promedio), 2) if row else 0,
            "num_ventas": row.cantidad if row else 0,
        })
    return result


# ─── Métricas de inventario ─────────────────────────────────────

def kpi_inventario(db: Session) -> dict:
    """KPIs de inventario: stock bajo, valor total, ingredientes por vencer."""
    from app.models.inventario import LoteIngrediente

    # Productos con stock bajo
    productos_bajo = db.query(Producto).filter(
        and_(
            Producto.activo.is_(True),
            Producto.stock_actual <= Producto.stock_minimo,
        )
    ).all()

    # Ingredientes con stock bajo
    ingredientes_bajo = db.query(Ingrediente).filter(
        and_(
            Ingrediente.activo.is_(True),
            Ingrediente.stock_actual <= Ingrediente.stock_minimo,
        )
    ).all()

    # Valor del inventario de productos
    valor_productos = db.query(
        func.sum(Producto.stock_actual * Producto.costo_produccion)
    ).filter(Producto.activo.is_(True)).scalar() or Decimal("0")

    # Lotes por vencer en 7 días
    prox_semana = date.today() + timedelta(days=7)
    lotes_por_vencer = db.query(func.count(LoteIngrediente.id)).filter(
        and_(
            LoteIngrediente.fecha_caducidad <= prox_semana,
            LoteIngrediente.fecha_caducidad >= date.today(),
            LoteIngrediente.cantidad_disponible > 0,
        )
    ).scalar() or 0

    return {
        "productos_stock_bajo": len(productos_bajo),
        "ingredientes_stock_bajo": len(ingredientes_bajo),
        "alertas_stock": [
            {"tipo": "producto", "nombre": p.nombre, "stock": float(p.stock_actual), "minimo": float(p.stock_minimo)}
            for p in productos_bajo[:10]
        ] + [
            {"tipo": "ingrediente", "nombre": i.nombre, "stock": float(i.stock_actual), "minimo": float(i.stock_minimo)}
            for i in ingredientes_bajo[:10]
        ],
        "valor_inventario_productos": _float(valor_productos),
        "lotes_por_vencer_7d": lotes_por_vencer,
    }


# ─── KPIs de clientes ───────────────────────────────────────────

def kpi_clientes(db: Session) -> dict:
    """Métricas de clientes: total, nuevos del mes, distribución niveles."""
    hoy = date.today()
    inicio_mes = date(hoy.year, hoy.month, 1)

    total_clientes = db.query(func.count(Cliente.id)).filter(
        Cliente.activo.is_(True)
    ).scalar() or 0

    nuevos_mes = db.query(func.count(Cliente.id)).filter(
        and_(
            Cliente.creado_en >= datetime.combine(inicio_mes, datetime.min.time()),
            Cliente.activo.is_(True),
        )
    ).scalar() or 0

    # Distribución por nivel de lealtad
    niveles = db.query(
        Cliente.nivel_lealtad, func.count(Cliente.id)
    ).filter(
        Cliente.activo.is_(True)
    ).group_by(Cliente.nivel_lealtad).all()

    return {
        "total_clientes": total_clientes,
        "nuevos_mes": nuevos_mes,
        "distribucion_niveles": [
            {"nivel": n[0] or "bronce", "cantidad": n[1]}
            for n in niveles
        ],
    }


# ─── Métodos de pago (para gráfica de dona) ────────────────────

def distribucion_metodos_pago(db: Session, dias: int = 30) -> list[dict]:
    """Distribución de métodos de pago."""
    inicio = datetime.combine(
        date.today() - timedelta(days=dias - 1), datetime.min.time()
    )
    fin = datetime.combine(date.today(), datetime.max.time())

    rows = db.query(
        Venta.metodo_pago,
        func.count(Venta.id).label("cantidad"),
        func.sum(Venta.total).label("total"),
    ).filter(
        and_(
            Venta.fecha >= inicio,
            Venta.fecha <= fin,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).group_by(Venta.metodo_pago).all()

    return [
        {
            "metodo": r.metodo_pago.value if hasattr(r.metodo_pago, "value") else str(r.metodo_pago),
            "cantidad": r.cantidad,
            "total": _float(r.total),
        }
        for r in rows
    ]


# ─── Dashboard KPIs consolidado ─────────────────────────────────

def dashboard_kpis(db: Session) -> dict:
    """Dashboard principal con todos los KPIs para gráficas."""
    hoy = date.today()
    inicio_hoy, fin_hoy = _rango_dia(hoy)
    inicio_mes = date(hoy.year, hoy.month, 1)

    # Ventas hoy
    ventas_hoy_row = db.query(
        func.sum(Venta.total).label("total"),
        func.count(Venta.id).label("cantidad"),
        func.avg(Venta.total).label("promedio"),
    ).filter(
        and_(
            Venta.fecha >= inicio_hoy,
            Venta.fecha <= fin_hoy,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).first()

    # Ventas mes
    ventas_mes = db.query(
        func.sum(Venta.total).label("total"),
        func.count(Venta.id).label("cantidad"),
    ).filter(
        and_(
            Venta.fecha >= datetime.combine(inicio_mes, datetime.min.time()),
            Venta.fecha <= fin_hoy,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).first()

    # Ayer para comparativo
    ayer = hoy - timedelta(days=1)
    inicio_ayer, fin_ayer = _rango_dia(ayer)
    ventas_ayer = db.query(
        func.sum(Venta.total)
    ).filter(
        and_(
            Venta.fecha >= inicio_ayer,
            Venta.fecha <= fin_ayer,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).scalar() or Decimal("0")

    total_hoy = _float(ventas_hoy_row.total) if ventas_hoy_row else 0
    total_ayer = _float(ventas_ayer)
    cambio_vs_ayer = 0.0
    if total_ayer > 0:
        cambio_vs_ayer = round((total_hoy - total_ayer) / total_ayer * 100, 1)

    return {
        "fecha": hoy.isoformat(),
        "ventas_hoy": {
            "total": total_hoy,
            "cantidad": ventas_hoy_row.cantidad if ventas_hoy_row else 0,
            "ticket_promedio": round(_float(ventas_hoy_row.promedio), 2) if ventas_hoy_row else 0,
            "cambio_vs_ayer_pct": cambio_vs_ayer,
        },
        "ventas_mes": {
            "total": _float(ventas_mes.total) if ventas_mes else 0,
            "cantidad": ventas_mes.cantidad if ventas_mes else 0,
        },
        "inventario": kpi_inventario(db),
        "clientes": kpi_clientes(db),
    }
