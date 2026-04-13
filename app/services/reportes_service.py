"""
Servicio de reportes financieros e impuestos.
Genera reportes de IVA, ISR, ventas y estado financiero.
"""

from decimal import Decimal
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract

from app.models.venta import Venta, DetalleVenta, EstadoVenta
from app.models.empleado import RegistroNomina
from app.models.inventario import MovimientoInventario, TipoMovimiento, Ingrediente


def gastos_hoy(db: Session, fecha: date | None = None) -> dict:
    """Retorna gastos del día (compras de ingredientes)."""
    from datetime import timezone
    dia = fecha or date.today()
    hoy_inicio = datetime.combine(dia, datetime.min.time(), tzinfo=timezone.utc)
    hoy_fin = datetime.combine(dia, datetime.max.time(), tzinfo=timezone.utc)

    compras = db.query(MovimientoInventario).filter(
        and_(
            MovimientoInventario.tipo == TipoMovimiento.ENTRADA_COMPRA,
            MovimientoInventario.fecha >= hoy_inicio,
            MovimientoInventario.fecha <= hoy_fin,
        )
    ).order_by(MovimientoInventario.fecha.desc()).all()

    total = sum(m.cantidad * m.costo_unitario for m in compras)

    desglose = []
    for m in compras:
        nombre = "Ingrediente"
        if m.ingrediente_id:
            ing = db.query(Ingrediente).filter(Ingrediente.id == m.ingrediente_id).first()
            if ing:
                nombre = ing.nombre
        desglose.append({
            "ingrediente": nombre,
            "cantidad": float(m.cantidad),
            "costo_unitario": float(m.costo_unitario),
            "total": float(m.cantidad * m.costo_unitario),
            "referencia": m.referencia,
            "hora": m.fecha.strftime("%H:%M") if m.fecha else "",
        })

    return {
        "total_gastos": float(total),
        "numero_compras": len(compras),
        "desglose": desglose,
    }


def reporte_ventas_periodo(db: Session, fecha_inicio: date, fecha_fin: date) -> dict:
    """Reporte de ventas por periodo con desglose fiscal."""
    ventas = db.query(Venta).filter(
        and_(
            Venta.fecha >= datetime.combine(fecha_inicio, datetime.min.time()),
            Venta.fecha <= datetime.combine(fecha_fin, datetime.max.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()

    total_ventas = sum(v.total for v in ventas)
    total_subtotal = sum(v.subtotal for v in ventas)
    total_iva_0 = sum(v.iva_0 for v in ventas)
    total_iva_16 = sum(v.iva_16 for v in ventas)
    total_descuentos = sum(v.descuento for v in ventas)

    # Desglose por método de pago
    por_metodo = {}
    for v in ventas:
        metodo = v.metodo_pago.value
        if metodo not in por_metodo:
            por_metodo[metodo] = {"cantidad": 0, "total": Decimal("0")}
        por_metodo[metodo]["cantidad"] += 1
        por_metodo[metodo]["total"] += v.total

    # Ventas por día
    por_dia = {}
    for v in ventas:
        dia = v.fecha.strftime("%Y-%m-%d")
        if dia not in por_dia:
            por_dia[dia] = {"cantidad": 0, "total": Decimal("0")}
        por_dia[dia]["cantidad"] += 1
        por_dia[dia]["total"] += v.total

    return {
        "periodo": {"inicio": fecha_inicio.isoformat(), "fin": fecha_fin.isoformat()},
        "resumen": {
            "numero_ventas": len(ventas),
            "subtotal": float(total_subtotal),
            "descuentos": float(total_descuentos),
            "iva_tasa_0_base": float(total_iva_0),
            "iva_tasa_16": float(total_iva_16),
            "total": float(total_ventas),
            "ticket_promedio": float(total_ventas / len(ventas)) if ventas else 0,
        },
        "por_metodo_pago": {
            k: {"cantidad": v["cantidad"], "total": float(v["total"])}
            for k, v in por_metodo.items()
        },
        "por_dia": {
            k: {"cantidad": v["cantidad"], "total": float(v["total"])}
            for k, v in sorted(por_dia.items())
        },
    }


def reporte_iva_mensual(db: Session, mes: int, anio: int) -> dict:
    """
    Reporte de IVA mensual para declaración.
    Separa operaciones gravadas al 0% y 16%.
    """
    fecha_inicio = date(anio, mes, 1)
    if mes == 12:
        fecha_fin = date(anio + 1, 1, 1)
    else:
        fecha_fin = date(anio, mes + 1, 1)

    ventas = db.query(Venta).filter(
        and_(
            Venta.fecha >= datetime.combine(fecha_inicio, datetime.min.time()),
            Venta.fecha < datetime.combine(fecha_fin, datetime.min.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()

    # IVA trasladado
    iva_trasladado_16 = sum(v.iva_16 for v in ventas)
    base_gravada_16 = Decimal("0")
    base_gravada_0 = sum(v.iva_0 for v in ventas)

    for v in ventas:
        for d in v.detalles:
            if d.tasa_iva > 0:
                base_gravada_16 += d.subtotal

    # IVA acreditable (simplificado - de compras de ingredientes)
    compras_periodo = db.query(
        func.sum(MovimientoInventario.cantidad * MovimientoInventario.costo_unitario)
    ).filter(
        and_(
            MovimientoInventario.tipo == TipoMovimiento.ENTRADA_COMPRA,
            MovimientoInventario.fecha >= fecha_inicio,
            MovimientoInventario.fecha < fecha_fin,
        )
    ).scalar() or Decimal("0")

    # Estimación IVA acreditable (16% de compras gravadas)
    iva_acreditable = (compras_periodo * Decimal("0.16")).quantize(Decimal("0.01"))

    iva_por_pagar = iva_trasladado_16 - iva_acreditable

    return {
        "periodo": f"{anio}-{mes:02d}",
        "iva_trasladado": {
            "tasa_16": {
                "base": float(base_gravada_16),
                "iva": float(iva_trasladado_16),
            },
            "tasa_0": {
                "base": float(base_gravada_0),
                "iva": 0,
            },
            "total_trasladado": float(iva_trasladado_16),
        },
        "iva_acreditable": float(iva_acreditable),
        "iva_por_pagar": float(max(iva_por_pagar, Decimal("0"))),
        "iva_a_favor": float(abs(min(iva_por_pagar, Decimal("0")))),
        "total_compras_periodo": float(compras_periodo),
    }


def reporte_isr_provisional(db: Session, mes: int, anio: int) -> dict:
    """ISR provisional mensual (simplificado para RESICO o Actividad Empresarial)."""
    fecha_inicio = date(anio, 1, 1)  # Acumulado desde enero
    if mes == 12:
        fecha_fin = date(anio + 1, 1, 1)
    else:
        fecha_fin = date(anio, mes + 1, 1)

    # Ingresos acumulados
    ingresos = db.query(func.sum(Venta.total)).filter(
        and_(
            Venta.fecha >= datetime.combine(fecha_inicio, datetime.min.time()),
            Venta.fecha < datetime.combine(fecha_fin, datetime.min.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).scalar() or Decimal("0")

    # Deducciones autorizadas (compras + nómina)
    compras = db.query(
        func.sum(MovimientoInventario.cantidad * MovimientoInventario.costo_unitario)
    ).filter(
        and_(
            MovimientoInventario.tipo == TipoMovimiento.ENTRADA_COMPRA,
            MovimientoInventario.fecha >= fecha_inicio,
            MovimientoInventario.fecha < fecha_fin,
        )
    ).scalar() or Decimal("0")

    nomina = db.query(func.sum(RegistroNomina.total_percepciones)).filter(
        and_(
            RegistroNomina.periodo_inicio >= fecha_inicio,
            RegistroNomina.periodo_fin < fecha_fin,
        )
    ).scalar() or Decimal("0")

    deducciones = compras + nomina
    utilidad = max(ingresos - deducciones, Decimal("0"))

    # ISR provisional (tasa simplificada RESICO)
    # Para RESICO tasas van de 1% a 2.5% según ingreso mensual
    tasa_provisional = Decimal("0.0125")  # 1.25% promedio estimado
    isr_provisional = (utilidad * tasa_provisional).quantize(Decimal("0.01"))

    return {
        "periodo": f"Enero - {['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'][mes]} {anio}",
        "ingresos_acumulados": float(ingresos),
        "deducciones_acumuladas": {
            "compras": float(compras),
            "nomina": float(nomina),
            "total": float(deducciones),
        },
        "utilidad_fiscal": float(utilidad),
        "tasa_provisional": float(tasa_provisional),
        "isr_provisional": float(isr_provisional),
    }


def reporte_productos_mas_vendidos(
    db: Session, fecha_inicio: date, fecha_fin: date, limit: int = 20,
) -> list[dict]:
    """Top productos más vendidos en un periodo."""
    from app.models.inventario import Producto

    resultados = (
        db.query(
            DetalleVenta.producto_id,
            Producto.nombre,
            func.sum(DetalleVenta.cantidad).label("total_cantidad"),
            func.sum(DetalleVenta.subtotal).label("total_ingresos"),
        )
        .join(Venta, DetalleVenta.venta_id == Venta.id)
        .join(Producto, DetalleVenta.producto_id == Producto.id)
        .filter(
            and_(
                Venta.fecha >= datetime.combine(fecha_inicio, datetime.min.time()),
                Venta.fecha <= datetime.combine(fecha_fin, datetime.max.time()),
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        )
        .group_by(DetalleVenta.producto_id, Producto.nombre)
        .order_by(func.sum(DetalleVenta.cantidad).desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "producto_id": r.producto_id,
            "nombre": r.nombre,
            "cantidad_vendida": float(r.total_cantidad),
            "ingresos": float(r.total_ingresos),
        }
        for r in resultados
    ]


def dashboard_resumen(db: Session) -> dict:
    """Resumen ejecutivo para el dashboard principal."""
    hoy = date.today()
    inicio_mes = date(hoy.year, hoy.month, 1)

    # Ventas del día
    ventas_hoy = db.query(func.sum(Venta.total)).filter(
        and_(
            Venta.fecha >= datetime.combine(hoy, datetime.min.time()),
            Venta.fecha <= datetime.combine(hoy, datetime.max.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).scalar() or Decimal("0")

    num_ventas_hoy = db.query(func.count(Venta.id)).filter(
        and_(
            Venta.fecha >= datetime.combine(hoy, datetime.min.time()),
            Venta.fecha <= datetime.combine(hoy, datetime.max.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).scalar() or 0

    # Ventas del mes
    ventas_mes = db.query(func.sum(Venta.total)).filter(
        and_(
            Venta.fecha >= datetime.combine(inicio_mes, datetime.min.time()),
            Venta.fecha <= datetime.combine(hoy, datetime.max.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).scalar() or Decimal("0")

    return {
        "fecha": hoy.isoformat(),
        "ventas_hoy": {
            "total": float(ventas_hoy),
            "numero_ventas": num_ventas_hoy,
        },
        "ventas_mes": {
            "total": float(ventas_mes),
        },
    }


def reporte_margenes_producto(db: Session) -> list[dict]:
    """Margen de ganancia por producto (precio venta - costo producción)."""
    from app.models.inventario import Producto
    productos = db.query(Producto).filter(Producto.activo.is_(True)).all()
    result = []
    for p in productos:
        precio = float(p.precio_unitario)
        costo = float(p.costo_produccion)
        margen = precio - costo
        pct = (margen / precio * 100) if precio > 0 else 0
        result.append({
            "id": p.id,
            "nombre": p.nombre,
            "precio": precio,
            "costo": costo,
            "margen": margen,
            "margen_pct": round(pct, 1),
            "stock": float(p.stock_actual),
        })
    result.sort(key=lambda x: x["margen_pct"], reverse=True)
    return result


def reporte_ventas_por_dia(db: Session, dias: int = 30) -> list[dict]:
    """Ventas diarias de los últimos N días."""
    from datetime import timedelta
    hoy = date.today()
    inicio = hoy - timedelta(days=dias - 1)
    ventas = db.query(Venta).filter(
        and_(
            Venta.fecha >= datetime.combine(inicio, datetime.min.time()),
            Venta.fecha <= datetime.combine(hoy, datetime.max.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()

    por_dia = {}
    for d in range(dias):
        dia = (inicio + timedelta(days=d)).isoformat()
        por_dia[dia] = {"total": 0, "tickets": 0}
    for v in ventas:
        dia = v.fecha.strftime("%Y-%m-%d")
        if dia in por_dia:
            por_dia[dia]["total"] += float(v.total)
            por_dia[dia]["tickets"] += 1

    return [{"fecha": k, "total": round(v["total"], 2), "tickets": v["tickets"]}
            for k, v in sorted(por_dia.items())]


def pronostico_produccion(db: Session) -> list[dict]:
    """Sugiere cuánto hornear hoy basado en ventas históricas del mismo día de la semana."""
    from datetime import timedelta
    from collections import defaultdict

    hoy = date.today()
    dia_semana = hoy.weekday()  # 0=lunes, 6=domingo

    # Obtener ventas de los últimos 28 días (4 semanas) del mismo día de la semana
    semanas = 4
    ventas_por_producto = defaultdict(list)

    for w in range(1, semanas + 1):
        dia = hoy - timedelta(weeks=w)
        inicio = datetime.combine(dia, datetime.min.time())
        fin = datetime.combine(dia, datetime.max.time())

        detalles = db.query(
            DetalleVenta.producto_id,
            func.sum(DetalleVenta.cantidad).label("total")
        ).join(Venta).filter(
            and_(
                Venta.fecha >= inicio,
                Venta.fecha <= fin,
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        ).group_by(DetalleVenta.producto_id).all()

        for d in detalles:
            ventas_por_producto[d.producto_id].append(float(d.total))

    from app.models.inventario import Producto
    result = []
    for prod_id, cantidades in ventas_por_producto.items():
        promedio = sum(cantidades) / len(cantidades)
        producto = db.query(Producto).filter(Producto.id == prod_id).first()
        if not producto or not producto.activo:
            continue
        stock = float(producto.stock_actual)
        sugerido = max(round(promedio * 1.1) - stock, 0)  # 10% extra margen
        result.append({
            "producto_id": prod_id,
            "nombre": producto.nombre,
            "stock_actual": stock,
            "promedio_venta_dia": round(promedio, 1),
            "sugerido_hornear": sugerido,
            "semanas_analizadas": len(cantidades),
        })

    result.sort(key=lambda x: x["sugerido_hornear"], reverse=True)
    return result


def alertas_caducidad(db: Session, dias: int = 7) -> list[dict]:
    """Ingredientes con lotes por caducar en los próximos N días."""
    from datetime import timedelta
    from app.models.inventario import LoteIngrediente, Ingrediente

    limite = date.today() + timedelta(days=dias)
    hoy = date.today()

    lotes = db.query(LoteIngrediente).filter(
        and_(
            LoteIngrediente.fecha_caducidad.isnot(None),
            LoteIngrediente.fecha_caducidad <= limite,
            LoteIngrediente.cantidad_disponible > 0,
        )
    ).order_by(LoteIngrediente.fecha_caducidad).all()

    result = []
    for lote in lotes:
        ing = db.query(Ingrediente).filter(Ingrediente.id == lote.ingrediente_id).first()
        dias_restantes = (lote.fecha_caducidad - hoy).days
        result.append({
            "lote_id": lote.id,
            "ingrediente": ing.nombre if ing else "Desconocido",
            "numero_lote": lote.numero_lote,
            "fecha_caducidad": lote.fecha_caducidad.isoformat(),
            "dias_restantes": dias_restantes,
            "cantidad_disponible": float(lote.cantidad_disponible),
            "vencido": dias_restantes < 0,
        })

    return result


def resumen_gastos_fijos(db: Session) -> dict:
    """Resumen de gastos fijos mensuales para cálculo de utilidad real."""
    from app.models.gasto_fijo import GastoFijo

    gastos = db.query(GastoFijo).filter(GastoFijo.activo.is_(True)).all()
    total_mensual = Decimal("0")
    desglose = []
    for g in gastos:
        monto_mensual = g.monto
        if g.periodicidad == "quincenal":
            monto_mensual = g.monto * 2
        elif g.periodicidad == "semanal":
            monto_mensual = g.monto * Decimal("4.33")
        total_mensual += monto_mensual
        desglose.append({
            "id": g.id,
            "concepto": g.concepto,
            "monto": float(g.monto),
            "periodicidad": g.periodicidad,
            "monto_mensual": float(monto_mensual.quantize(Decimal("0.01"))),
        })

    return {
        "total_mensual": float(total_mensual.quantize(Decimal("0.01"))),
        "total_diario": float((total_mensual / 30).quantize(Decimal("0.01"))),
        "gastos": desglose,
    }


def historial_compras_cliente(db: Session, cliente_id: int) -> dict:
    """Historial de compras de un cliente con totales."""
    from app.models.cliente import Cliente

    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        return {"error": "Cliente no encontrado"}

    ventas = db.query(Venta).filter(
        and_(
            Venta.cliente_id == cliente_id,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).order_by(Venta.fecha.desc()).limit(50).all()

    total_compras = sum(v.total for v in ventas)

    return {
        "cliente": {
            "id": cliente.id,
            "nombre": cliente.nombre,
            "telefono": cliente.telefono,
            "email": cliente.email,
            "puntos": cliente.puntos_acumulados,
        },
        "total_compras": float(total_compras),
        "numero_visitas": len(ventas),
        "ticket_promedio": float(total_compras / len(ventas)) if ventas else 0,
        "ultima_visita": ventas[0].fecha.isoformat() if ventas else None,
        "compras": [
            {
                "id": v.id,
                "folio": v.folio,
                "total": float(v.total),
                "fecha": v.fecha.strftime("%Y-%m-%d %H:%M"),
                "metodo_pago": v.metodo_pago.value,
            }
            for v in ventas
        ],
    }
