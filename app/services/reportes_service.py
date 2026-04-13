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
