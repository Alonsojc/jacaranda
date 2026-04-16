"""Servicio de dashboard ejecutivo - vista consolidada para dueño del negocio."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.venta import Venta, DetalleVenta, EstadoVenta
from app.models.pedido import Pedido, EstadoPedido
from app.models.inventario import Producto, Ingrediente, LoteIngrediente
from app.models.cliente import Cliente
from app.models.empleado import Empleado
from app.models.merma import RegistroMerma


def _float(v) -> float:
    if v is None:
        return 0.0
    return float(v)


def _rango_dia(dia: date):
    return (
        datetime.combine(dia, datetime.min.time()),
        datetime.combine(dia, datetime.max.time()),
    )


def dashboard_ejecutivo(db: Session) -> dict:
    """Dashboard completo para el dueño del negocio."""
    hoy = date.today()
    ayer = hoy - timedelta(days=1)
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = date(hoy.year, hoy.month, 1)

    inicio_hoy, fin_hoy = _rango_dia(hoy)
    inicio_ayer, fin_ayer = _rango_dia(ayer)

    # ── Ventas ──
    def _ventas_rango(inicio, fin):
        row = db.query(
            func.sum(Venta.total).label("total"),
            func.count(Venta.id).label("cantidad"),
            func.avg(Venta.total).label("promedio"),
        ).filter(
            and_(Venta.fecha >= inicio, Venta.fecha <= fin,
                 Venta.estado == EstadoVenta.COMPLETADA)
        ).first()
        return row

    v_hoy = _ventas_rango(inicio_hoy, fin_hoy)
    v_ayer = _ventas_rango(inicio_ayer, fin_ayer)
    v_semana = _ventas_rango(
        datetime.combine(inicio_semana, datetime.min.time()), fin_hoy
    )
    v_mes = _ventas_rango(
        datetime.combine(inicio_mes, datetime.min.time()), fin_hoy
    )

    total_hoy = _float(v_hoy.total)
    total_ayer = _float(v_ayer.total)
    cambio = round((total_hoy - total_ayer) / total_ayer * 100, 1) if total_ayer > 0 else 0.0

    # ── Pedidos ──
    pedidos_pendientes = db.query(func.count(Pedido.id)).filter(
        Pedido.estado == EstadoPedido.RECIBIDO).scalar() or 0
    pedidos_prep = db.query(func.count(Pedido.id)).filter(
        Pedido.estado == EstadoPedido.EN_PREPARACION).scalar() or 0
    pedidos_listos = db.query(func.count(Pedido.id)).filter(
        Pedido.estado == EstadoPedido.LISTO).scalar() or 0
    pedidos_entregados_hoy = db.query(func.count(Pedido.id)).filter(
        and_(Pedido.estado == EstadoPedido.ENTREGADO,
             Pedido.fecha_entrega == hoy)).scalar() or 0
    pedidos_mes = db.query(func.count(Pedido.id)).filter(
        Pedido.creado_en >= datetime.combine(inicio_mes, datetime.min.time())
    ).scalar() or 0

    # ── Inventario ──
    productos_bajo = db.query(func.count(Producto.id)).filter(
        and_(Producto.activo.is_(True),
             Producto.stock_actual <= Producto.stock_minimo)).scalar() or 0
    ingredientes_bajo = db.query(func.count(Ingrediente.id)).filter(
        and_(Ingrediente.activo.is_(True),
             Ingrediente.stock_actual <= Ingrediente.stock_minimo)).scalar() or 0
    valor_inv = db.query(
        func.sum(Producto.stock_actual * Producto.precio_unitario)
    ).filter(Producto.activo.is_(True)).scalar() or Decimal("0")
    lotes_vencer = db.query(func.count(LoteIngrediente.id)).filter(
        and_(LoteIngrediente.fecha_caducidad <= hoy + timedelta(days=7),
             LoteIngrediente.fecha_caducidad >= hoy,
             LoteIngrediente.cantidad_disponible > 0)).scalar() or 0

    # ── Finanzas ──
    costo_merma = db.query(func.sum(RegistroMerma.costo_total)).filter(
        RegistroMerma.fecha_merma >= inicio_mes
    ).scalar() or Decimal("0")

    margen_rows = db.query(
        func.sum(DetalleVenta.subtotal).label("ingresos"),
        func.sum(DetalleVenta.cantidad * Producto.costo_produccion).label("costos"),
    ).join(Venta).join(Producto, DetalleVenta.producto_id == Producto.id).filter(
        and_(Venta.fecha >= datetime.combine(inicio_mes, datetime.min.time()),
             Venta.estado == EstadoVenta.COMPLETADA)
    ).first()
    ingresos_mes = _float(margen_rows.ingresos) if margen_rows else 0
    costos_mes = _float(margen_rows.costos) if margen_rows else 0
    margen_pct = round((ingresos_mes - costos_mes) / ingresos_mes * 100, 1) if ingresos_mes > 0 else 0

    ticket_prom_mes = _float(v_mes.promedio) if v_mes else 0

    # ── Clientes ──
    total_clientes = db.query(func.count(Cliente.id)).filter(
        Cliente.activo.is_(True)).scalar() or 0
    nuevos_mes = db.query(func.count(Cliente.id)).filter(
        and_(Cliente.creado_en >= datetime.combine(inicio_mes, datetime.min.time()),
             Cliente.activo.is_(True))).scalar() or 0

    # Satisfacción promedio
    from app.models.crm import EncuestaSatisfaccion
    sat_prom = db.query(func.avg(EncuestaSatisfaccion.calificacion)).scalar()

    # ── Empleados ──
    total_empleados = db.query(func.count(Empleado.id)).filter(
        Empleado.activo.is_(True)).scalar() or 0

    # ── Alertas ──
    alertas = []
    if productos_bajo > 0:
        alertas.append({"tipo": "stock_bajo", "mensaje": f"{productos_bajo} producto(s) con stock bajo", "severidad": "alta"})
    if ingredientes_bajo > 0:
        alertas.append({"tipo": "stock_bajo", "mensaje": f"{ingredientes_bajo} ingrediente(s) con stock bajo", "severidad": "alta"})
    if lotes_vencer > 0:
        alertas.append({"tipo": "caducidad", "mensaje": f"{lotes_vencer} lote(s) por vencer en 7 días", "severidad": "media"})
    if pedidos_pendientes > 3:
        alertas.append({"tipo": "pedidos", "mensaje": f"{pedidos_pendientes} pedidos pendientes de confirmar", "severidad": "media"})
    if _float(costo_merma) > 1000:
        alertas.append({"tipo": "merma", "mensaje": f"Merma del mes: ${_float(costo_merma):,.0f}", "severidad": "media"})

    return {
        "fecha": hoy.isoformat(),
        "ventas": {
            "hoy": total_hoy, "ayer": total_ayer,
            "semana": _float(v_semana.total),
            "mes": _float(v_mes.total),
            "tickets_hoy": v_hoy.cantidad if v_hoy else 0,
            "ticket_promedio": round(_float(v_hoy.promedio), 2) if v_hoy else 0,
            "cambio_vs_ayer_pct": cambio,
        },
        "pedidos": {
            "pendientes": pedidos_pendientes,
            "en_preparacion": pedidos_prep,
            "listos": pedidos_listos,
            "entregados_hoy": pedidos_entregados_hoy,
            "total_mes": pedidos_mes,
        },
        "inventario": {
            "productos_stock_bajo": productos_bajo,
            "ingredientes_stock_bajo": ingredientes_bajo,
            "valor_inventario": _float(valor_inv),
            "lotes_por_vencer": lotes_vencer,
        },
        "finanzas": {
            "ingresos_mes": ingresos_mes,
            "costo_merma_mes": _float(costo_merma),
            "margen_promedio_pct": margen_pct,
            "ticket_promedio_mes": round(ticket_prom_mes, 2),
        },
        "clientes": {
            "total_activos": total_clientes,
            "nuevos_mes": nuevos_mes,
            "satisfaccion_promedio": round(_float(sat_prom), 1),
        },
        "empleados": {"total_activos": total_empleados},
        "alertas": alertas[:10],
    }


def resumen_semanal(db: Session) -> list[dict]:
    """Totales diarios de los últimos 7 días."""
    result = []
    hoy = date.today()
    for i in range(6, -1, -1):
        dia = hoy - timedelta(days=i)
        inicio, fin = _rango_dia(dia)
        row = db.query(
            func.sum(Venta.total).label("total"),
            func.count(Venta.id).label("cantidad"),
        ).filter(
            and_(Venta.fecha >= inicio, Venta.fecha <= fin,
                 Venta.estado == EstadoVenta.COMPLETADA)
        ).first()
        pedidos = db.query(func.count(Pedido.id)).filter(
            Pedido.fecha_entrega == dia).scalar() or 0
        result.append({
            "fecha": dia.isoformat(),
            "ventas": _float(row.total) if row else 0,
            "tickets": row.cantidad if row else 0,
            "pedidos": pedidos,
        })
    return result


def comparativo_periodos(db: Session, dias: int = 30) -> dict:
    """Compara período actual vs anterior."""
    hoy = date.today()
    inicio_actual = hoy - timedelta(days=dias - 1)
    fin_actual = hoy
    inicio_anterior = inicio_actual - timedelta(days=dias)
    fin_anterior = inicio_actual - timedelta(days=1)

    def _stats(inicio, fin):
        row = db.query(
            func.sum(Venta.total).label("total"),
            func.count(Venta.id).label("cantidad"),
        ).filter(
            and_(
                Venta.fecha >= datetime.combine(inicio, datetime.min.time()),
                Venta.fecha <= datetime.combine(fin, datetime.max.time()),
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        ).first()
        return {"ventas": _float(row.total), "tickets": row.cantidad if row else 0}

    actual = _stats(inicio_actual, fin_actual)
    anterior = _stats(inicio_anterior, fin_anterior)
    cambio = 0.0
    if anterior["ventas"] > 0:
        cambio = round((actual["ventas"] - anterior["ventas"]) / anterior["ventas"] * 100, 1)

    return {"actual": actual, "anterior": anterior, "cambio_pct": cambio, "dias": dias}
