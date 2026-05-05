"""
Servicio de reportes financieros e impuestos.
Genera reportes de IVA, ISR, ventas y estado financiero.
"""

from decimal import Decimal
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, extract

from app.core.db_compat import db_extract_dow
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
    """
    ISR provisional mensual — Persona Moral, Régimen 601.
    Art. 14 LISR: Pagos provisionales = Ingresos nominales acumulados
    × Coeficiente de utilidad × Tasa 30%.
    """
    fecha_inicio = date(anio, 1, 1)  # Acumulado desde enero
    if mes == 12:
        fecha_fin = date(anio + 1, 1, 1)
    else:
        fecha_fin = date(anio, mes + 1, 1)

    # Ingresos nominales acumulados (sin IVA)
    from app.models.inventario import Producto
    ventas = db.query(Venta).filter(
        and_(
            Venta.fecha >= datetime.combine(fecha_inicio, datetime.min.time()),
            Venta.fecha < datetime.combine(fecha_fin, datetime.min.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()
    ingresos_brutos = sum((v.total or Decimal("0")) for v in ventas)
    iva_cobrado = sum((v.iva_16 or Decimal("0")) for v in ventas)
    ingresos_nominales = ingresos_brutos - iva_cobrado

    # Deducciones autorizadas (compras + nómina + gastos fijos)
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

    # Gastos fijos prorrateados al periodo
    from app.models.gasto_fijo import GastoFijo
    gastos_fijos = db.query(GastoFijo).filter(GastoFijo.activo.is_(True)).all()
    total_gastos_fijos = Decimal("0")
    for g in gastos_fijos:
        if g.periodicidad == "mensual":
            total_gastos_fijos += g.monto * mes
        elif g.periodicidad == "quincenal":
            total_gastos_fijos += g.monto * mes * 2
        elif g.periodicidad == "semanal":
            total_gastos_fijos += g.monto * mes * Decimal("4.33")

    deducciones = compras + nomina + total_gastos_fijos
    utilidad_fiscal = max(ingresos_nominales - deducciones, Decimal("0"))

    # Coeficiente de utilidad (Art. 14 LISR)
    # CU = Utilidad fiscal del ejercicio anterior / Ingresos nominales anterior
    # Primer ejercicio o sin datos: usar utilidad actual como estimación
    coeficiente_utilidad = Decimal("0.30")  # Default conservador primer ejercicio
    if ingresos_nominales > 0:
        cu_calculado = utilidad_fiscal / ingresos_nominales
        if cu_calculado > 0:
            coeficiente_utilidad = min(cu_calculado, Decimal("0.90"))

    # Base para pago provisional
    base_provisional = ingresos_nominales * coeficiente_utilidad

    # Tasa ISR Personas Morales: 30% (Art. 9 LISR)
    tasa_isr = Decimal("0.30")
    isr_provisional = (base_provisional * tasa_isr).quantize(Decimal("0.01"))

    # PTU por pagar (10% de utilidad fiscal, Art. 9 LISR / Art. 120 LFT)
    ptu_estimado = (utilidad_fiscal * Decimal("0.10")).quantize(Decimal("0.01"))

    meses = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
             'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

    return {
        "regimen": "601 - General de Ley Personas Morales",
        "periodo": f"Enero - {meses[mes]} {anio}",
        "ingresos_acumulados": float(ingresos_nominales),
        "ingresos_brutos": float(ingresos_brutos),
        "iva_cobrado": float(iva_cobrado),
        "deducciones_acumuladas": {
            "compras": float(compras),
            "nomina": float(nomina),
            "gastos_fijos": float(total_gastos_fijos),
            "total": float(deducciones),
        },
        "utilidad_fiscal": float(utilidad_fiscal),
        "coeficiente_utilidad": float(coeficiente_utilidad),
        "base_provisional": float(base_provisional),
        "tasa_provisional": float(tasa_isr),
        "isr_provisional": float(isr_provisional),
        "ptu_estimado": float(ptu_estimado),
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
    from app.models.pedido import DetallePedido, EstadoPedido, Pedido

    hoy = date.today()

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

    reservas = {
        row.producto_id: int(row.total or 0)
        for row in db.query(
            DetallePedido.producto_id,
            func.sum(DetallePedido.cantidad).label("total"),
        ).join(Pedido, Pedido.id == DetallePedido.pedido_id).filter(
            and_(
                Pedido.fecha_entrega == hoy,
                Pedido.estado.in_([
                    EstadoPedido.RECIBIDO,
                    EstadoPedido.CONFIRMADO,
                    EstadoPedido.EN_PREPARACION,
                    EstadoPedido.LISTO,
                    EstadoPedido.EN_RUTA,
                ]),
                DetallePedido.producto_id.isnot(None),
            )
        ).group_by(DetallePedido.producto_id).all()
    }

    from app.models.inventario import Producto
    result = []
    for prod_id in set(ventas_por_producto.keys()) | set(reservas.keys()):
        cantidades = ventas_por_producto.get(prod_id, [])
        promedio = sum(cantidades) / len(cantidades) if cantidades else 0
        producto = db.query(Producto).filter(Producto.id == prod_id).first()
        if not producto or not producto.activo:
            continue
        stock = float(producto.stock_actual)
        reservado = reservas.get(prod_id, 0)
        demanda_total = round(promedio * 1.1) + reservado
        sugerido = max(demanda_total - stock, 0)  # 10% extra margen + pedidos de hoy
        receta = producto.receta
        result.append({
            "producto_id": prod_id,
            "nombre": producto.nombre,
            "stock_actual": stock,
            "promedio_venta_dia": round(promedio, 1),
            "reservado_pedidos": reservado,
            "demanda_total": demanda_total,
            "sugerido_hornear": sugerido,
            "semanas_analizadas": len(cantidades),
            "tiene_receta": bool(receta and receta.activo),
            "receta_completa": bool(receta and receta.activo and receta.ingredientes),
            "costo_ok": producto.costo_produccion > 0,
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


# ─── Reporte de mermas ─────────────────────────────────────────────

def reporte_mermas(
    db: Session, dias: int = 30,
) -> dict:
    """Resumen de mermas en los últimos N días."""
    from datetime import timedelta
    from app.models.inventario import Producto

    limite = datetime.combine(
        date.today() - timedelta(days=dias), datetime.min.time(),
    )

    mermas = db.query(MovimientoInventario).filter(
        and_(
            MovimientoInventario.tipo.in_([
                TipoMovimiento.SALIDA_MERMA,
                TipoMovimiento.SALIDA_CADUCIDAD,
            ]),
            MovimientoInventario.fecha >= limite,
        )
    ).order_by(MovimientoInventario.fecha.desc()).all()

    # Aggregate by product/ingredient
    por_producto: dict[int, dict] = {}
    total_unidades = 0
    total_costo = Decimal("0")

    for m in mermas:
        if m.producto_id:
            key = ("producto", m.producto_id)
        elif m.ingrediente_id:
            key = ("ingrediente", m.ingrediente_id)
        else:
            continue

        if key not in por_producto:
            nombre = "Desconocido"
            costo_ref = Decimal("0")
            if m.producto_id:
                prod = db.query(Producto).filter(Producto.id == m.producto_id).first()
                if prod:
                    nombre = prod.nombre
                    costo_ref = prod.costo_produccion
            elif m.ingrediente_id:
                ing = db.query(Ingrediente).filter(Ingrediente.id == m.ingrediente_id).first()
                if ing:
                    nombre = ing.nombre
                    costo_ref = ing.costo_unitario
            por_producto[key] = {
                "tipo": key[0], "id": key[1], "nombre": nombre,
                "total_cantidad": 0, "costo_estimado": Decimal("0"),
                "costo_unitario_ref": float(costo_ref), "movimientos": 0,
            }

        costo_u = m.costo_unitario if m.costo_unitario else Decimal(str(por_producto[key]["costo_unitario_ref"]))
        por_producto[key]["total_cantidad"] += float(m.cantidad)
        por_producto[key]["costo_estimado"] += m.cantidad * costo_u
        por_producto[key]["movimientos"] += 1
        total_unidades += float(m.cantidad)
        total_costo += m.cantidad * costo_u

    desglose = sorted(por_producto.values(), key=lambda x: x["costo_estimado"], reverse=True)
    for item in desglose:
        item["costo_estimado"] = float(item["costo_estimado"])

    return {
        "dias": dias,
        "total_mermas": len(mermas),
        "total_unidades": total_unidades,
        "costo_total_estimado": float(total_costo),
        "desglose": desglose,
        "detalle": [
            {
                "id": m.id,
                "tipo": m.tipo.value,
                "producto_id": m.producto_id,
                "ingrediente_id": m.ingrediente_id,
                "cantidad": float(m.cantidad),
                "referencia": m.referencia,
                "notas": m.notas,
                "fecha": m.fecha.strftime("%Y-%m-%d %H:%M") if m.fecha else "",
            }
            for m in mermas[:100]  # Limit detail to 100
        ],
    }


# ─── Kardex de ingrediente ─────────────────────────────────────────

def kardex_ingrediente(db: Session, ingrediente_id: int, limit: int = 100) -> dict:
    """Historial de movimientos con saldo acumulado para un ingrediente."""
    ing = db.query(Ingrediente).filter(Ingrediente.id == ingrediente_id).first()
    if not ing:
        raise ValueError("Ingrediente no encontrado")

    movimientos = db.query(MovimientoInventario).filter(
        MovimientoInventario.ingrediente_id == ingrediente_id,
    ).order_by(MovimientoInventario.fecha.asc()).all()

    kardex = []
    saldo = Decimal("0")
    tipo_labels = {
        "entrada_compra": "Compra",
        "entrada_produccion": "Producción",
        "entrada_devolucion": "Devolución",
        "entrada_ajuste": "Ajuste +",
        "salida_venta": "Venta",
        "salida_produccion": "Uso receta",
        "salida_merma": "Merma",
        "salida_ajuste": "Ajuste -",
        "salida_caducidad": "Caducidad",
    }

    for m in movimientos:
        es_entrada = m.tipo.value.startswith("entrada")
        cantidad = float(m.cantidad)
        saldo += m.cantidad if es_entrada else -m.cantidad
        kardex.append({
            "id": m.id,
            "fecha": m.fecha.strftime("%Y-%m-%d %H:%M") if m.fecha else "",
            "tipo": tipo_labels.get(m.tipo.value, m.tipo.value),
            "entrada": cantidad if es_entrada else 0,
            "salida": 0 if es_entrada else cantidad,
            "saldo": float(saldo),
            "costo_unitario": float(m.costo_unitario),
            "referencia": m.referencia or "",
        })

    # Return last N entries (most recent) but keep correct saldo
    kardex_reciente = kardex[-limit:] if len(kardex) > limit else kardex

    return {
        "ingrediente_id": ing.id,
        "nombre": ing.nombre,
        "unidad_medida": ing.unidad_medida.value,
        "stock_actual": float(ing.stock_actual),
        "total_movimientos": len(movimientos),
        "kardex": kardex_reciente,
    }


# ─── Dashboard de empleados ────────────────────────────────────────

def dashboard_empleados(db: Session) -> dict:
    """Resumen de empleados: cumpleaños próximos, documentos por vencer."""
    from datetime import timedelta
    from app.models.empleado import Empleado

    hoy = date.today()
    empleados = db.query(Empleado).filter(Empleado.activo.is_(True)).all()

    cumpleanios = []
    docs_por_vencer = []
    resumen = {
        "total_activos": len(empleados),
        "por_departamento": {},
    }

    for emp in empleados:
        # Count by department
        dept = emp.departamento.value if emp.departamento else "otro"
        resumen["por_departamento"][dept] = resumen["por_departamento"].get(dept, 0) + 1

        # Birthdays in next 30 days
        if emp.fecha_nacimiento:
            cumple_este_anio = emp.fecha_nacimiento.replace(year=hoy.year)
            if cumple_este_anio < hoy:
                cumple_este_anio = cumple_este_anio.replace(year=hoy.year + 1)
            dias_para = (cumple_este_anio - hoy).days
            if dias_para <= 30:
                edad = hoy.year - emp.fecha_nacimiento.year
                cumpleanios.append({
                    "nombre": f"{emp.nombre} {emp.apellido_paterno}",
                    "fecha": cumple_este_anio.strftime("%d/%m"),
                    "dias_para": dias_para,
                    "edad": edad,
                })

        # Health card / medical revision
        if emp.fecha_ultima_revision_medica:
            dias_desde = (hoy - emp.fecha_ultima_revision_medica).days
            if dias_desde > 330:  # Alert 35 days before annual renewal
                docs_por_vencer.append({
                    "empleado": f"{emp.nombre} {emp.apellido_paterno}",
                    "documento": "Revisión médica",
                    "fecha": emp.fecha_ultima_revision_medica.isoformat(),
                    "dias_vencido": dias_desde - 365 if dias_desde > 365 else 0,
                    "urgente": dias_desde > 365,
                })
        elif emp.tiene_tarjeta_salud:
            docs_por_vencer.append({
                "empleado": f"{emp.nombre} {emp.apellido_paterno}",
                "documento": "Revisión médica",
                "fecha": None,
                "dias_vencido": 0,
                "urgente": True,
            })

        # Hygiene training
        if emp.fecha_capacitacion_higiene:
            dias_desde_cap = (hoy - emp.fecha_capacitacion_higiene).days
            if dias_desde_cap > 330:
                docs_por_vencer.append({
                    "empleado": f"{emp.nombre} {emp.apellido_paterno}",
                    "documento": "Capacitación higiene",
                    "fecha": emp.fecha_capacitacion_higiene.isoformat(),
                    "dias_vencido": dias_desde_cap - 365 if dias_desde_cap > 365 else 0,
                    "urgente": dias_desde_cap > 365,
                })
        elif not emp.capacitacion_higiene:
            docs_por_vencer.append({
                "empleado": f"{emp.nombre} {emp.apellido_paterno}",
                "documento": "Capacitación higiene pendiente",
                "fecha": None,
                "dias_vencido": 0,
                "urgente": True,
            })

    cumpleanios.sort(key=lambda x: x["dias_para"])
    docs_por_vencer.sort(key=lambda x: (not x["urgente"], -x.get("dias_vencido", 0)))

    return {
        "resumen": resumen,
        "cumpleanios": cumpleanios,
        "documentos_por_vencer": docs_por_vencer,
    }


# ─── Ventas por hora ──────────────────────────────────────────────

def reporte_ventas_por_hora(db: Session, dias: int = 7) -> list[dict]:
    """Ventas agrupadas por hora del día (últimos N días)."""
    from datetime import timedelta
    from app.models.inventario import Producto

    hoy = date.today()
    inicio = datetime.combine(hoy - timedelta(days=dias - 1), datetime.min.time())
    fin = datetime.combine(hoy, datetime.max.time())

    ventas = db.query(Venta).filter(
        and_(
            Venta.fecha >= inicio,
            Venta.fecha <= fin,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()

    por_hora: dict[int, dict] = {}
    for h in range(24):
        por_hora[h] = {"hora": h, "total": 0, "tickets": 0}

    for v in ventas:
        hora = v.fecha.hour if v.fecha else 0
        por_hora[hora]["total"] += float(v.total)
        por_hora[hora]["tickets"] += 1

    return [por_hora[h] for h in range(24)]


# ─── Análisis ABC de inventario ───────────────────────────────────

def analisis_abc(db: Session, dias: int = 30) -> dict:
    """Análisis ABC (Pareto 80/20) de productos por ingresos."""
    from datetime import timedelta
    from app.models.inventario import Producto

    hoy = date.today()
    inicio = datetime.combine(hoy - timedelta(days=dias - 1), datetime.min.time())
    fin = datetime.combine(hoy, datetime.max.time())

    detalles = db.query(DetalleVenta).join(Venta).filter(
        and_(
            Venta.fecha >= inicio,
            Venta.fecha <= fin,
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()

    # Aggregate by product
    por_prod: dict[int, dict] = {}
    ingreso_total = Decimal("0")
    for d in detalles:
        pid = d.producto_id
        if pid not in por_prod:
            prod = db.query(Producto).filter(Producto.id == pid).first()
            por_prod[pid] = {
                "producto_id": pid,
                "nombre": prod.nombre if prod else f"Producto #{pid}",
                "ingresos": Decimal("0"),
                "cantidad": Decimal("0"),
                "costo": Decimal("0"),
                "costo_unitario": prod.costo_produccion if prod else Decimal("0"),
            }
        por_prod[pid]["ingresos"] += d.subtotal
        por_prod[pid]["cantidad"] += d.cantidad
        por_prod[pid]["costo"] += d.cantidad * por_prod[pid]["costo_unitario"]
        ingreso_total += d.subtotal

    # Sort by revenue descending
    productos = sorted(por_prod.values(), key=lambda x: x["ingresos"], reverse=True)

    # Classify ABC
    acumulado = Decimal("0")
    for p in productos:
        acumulado += p["ingresos"]
        pct_acum = float(acumulado / ingreso_total * 100) if ingreso_total > 0 else 0
        utilidad = p["ingresos"] - p["costo"]
        p["clase"] = "A" if pct_acum <= 80 else ("B" if pct_acum <= 95 else "C")
        p["pct_ingresos"] = round(float(p["ingresos"] / ingreso_total * 100), 1) if ingreso_total else 0
        p["pct_acumulado"] = round(pct_acum, 1)
        p["ingresos"] = float(p["ingresos"])
        p["cantidad"] = float(p["cantidad"])
        p["utilidad"] = float(utilidad)
        p["costo"] = float(p["costo"])
        del p["costo_unitario"]

    conteo = {"A": 0, "B": 0, "C": 0}
    for p in productos:
        conteo[p["clase"]] += 1

    return {
        "dias": dias,
        "total_ingresos": float(ingreso_total),
        "total_productos": len(productos),
        "conteo_abc": conteo,
        "productos": productos,
    }


# ─── Dashboard avanzado ──────────────────────────────────────────

def dashboard_avanzado(db: Session) -> dict:
    """Dashboard con comparativos mensuales, proyección y clientes top."""
    from datetime import timedelta
    from app.models.inventario import Producto
    from app.models.cliente import Cliente
    from app.models.gasto_fijo import GastoFijo

    hoy = date.today()

    # --- Comparativo: este mes vs mes anterior ---
    inicio_mes = date(hoy.year, hoy.month, 1)
    if hoy.month == 1:
        inicio_mes_ant = date(hoy.year - 1, 12, 1)
        fin_mes_ant = date(hoy.year - 1, 12, 31)
    else:
        inicio_mes_ant = date(hoy.year, hoy.month - 1, 1)
        fin_mes_ant = inicio_mes - timedelta(days=1)

    ventas_este_mes = db.query(
        func.sum(Venta.total), func.count(Venta.id)
    ).filter(
        and_(
            Venta.fecha >= datetime.combine(inicio_mes, datetime.min.time()),
            Venta.fecha <= datetime.combine(hoy, datetime.max.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).first()

    ventas_mes_ant = db.query(
        func.sum(Venta.total), func.count(Venta.id)
    ).filter(
        and_(
            Venta.fecha >= datetime.combine(inicio_mes_ant, datetime.min.time()),
            Venta.fecha <= datetime.combine(fin_mes_ant, datetime.max.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).first()

    total_este_mes = float(ventas_este_mes[0] or 0)
    tickets_este_mes = ventas_este_mes[1] or 0
    total_mes_ant = float(ventas_mes_ant[0] or 0)
    tickets_mes_ant = ventas_mes_ant[1] or 0

    cambio_pct = 0.0
    if total_mes_ant > 0:
        cambio_pct = round((total_este_mes - total_mes_ant) / total_mes_ant * 100, 1)

    # --- Proyección mensual ---
    dias_transcurridos = (hoy - inicio_mes).days + 1
    import calendar
    dias_del_mes = calendar.monthrange(hoy.year, hoy.month)[1]
    proyeccion_mes = round(total_este_mes / dias_transcurridos * dias_del_mes, 2) if dias_transcurridos > 0 else 0

    # --- Ventas últimos 12 meses para gráfica ---
    meses = []
    for i in range(11, -1, -1):
        m = hoy.month - i
        y = hoy.year
        while m <= 0:
            m += 12
            y -= 1
        mes_inicio = date(y, m, 1)
        if m == 12:
            mes_fin = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            mes_fin = date(y, m + 1, 1) - timedelta(days=1)

        total_mes = db.query(func.sum(Venta.total)).filter(
            and_(
                Venta.fecha >= datetime.combine(mes_inicio, datetime.min.time()),
                Venta.fecha <= datetime.combine(mes_fin, datetime.max.time()),
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        ).scalar() or Decimal("0")

        nombres_mes = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                        'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        meses.append({
            "mes": f"{nombres_mes[m]} {y}",
            "total": float(total_mes),
        })

    # --- Top 10 clientes VIP ---
    top_clientes = db.query(
        Venta.cliente_id,
        func.sum(Venta.total).label("total"),
        func.count(Venta.id).label("visitas"),
    ).filter(
        and_(
            Venta.cliente_id.isnot(None),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).group_by(Venta.cliente_id).order_by(
        func.sum(Venta.total).desc()
    ).limit(10).all()

    clientes_vip = []
    for tc in top_clientes:
        cliente = db.query(Cliente).filter(Cliente.id == tc.cliente_id).first()
        if cliente:
            clientes_vip.append({
                "id": cliente.id,
                "nombre": cliente.nombre,
                "telefono": cliente.telefono,
                "puntos": cliente.puntos_acumulados,
                "total_compras": float(tc.total),
                "visitas": tc.visitas,
                "ticket_promedio": round(float(tc.total) / tc.visitas, 2),
            })

    # --- Utilidad estimada (ventas - costos - gastos fijos) ---
    costo_ventas = Decimal("0")
    detalles_mes = db.query(DetalleVenta).join(Venta).filter(
        and_(
            Venta.fecha >= datetime.combine(inicio_mes, datetime.min.time()),
            Venta.fecha <= datetime.combine(hoy, datetime.max.time()),
            Venta.estado == EstadoVenta.COMPLETADA,
        )
    ).all()
    for d in detalles_mes:
        prod = db.query(Producto).filter(Producto.id == d.producto_id).first()
        if prod:
            costo_ventas += d.cantidad * prod.costo_produccion

    gastos_fijos = db.query(GastoFijo).filter(GastoFijo.activo.is_(True)).all()
    total_gastos_fijos = Decimal("0")
    for g in gastos_fijos:
        if g.periodicidad == "quincenal":
            total_gastos_fijos += g.monto * 2
        elif g.periodicidad == "semanal":
            total_gastos_fijos += g.monto * Decimal("4.33")
        else:
            total_gastos_fijos += g.monto

    utilidad_bruta = Decimal(str(total_este_mes)) - costo_ventas
    utilidad_neta = utilidad_bruta - total_gastos_fijos

    return {
        "comparativo": {
            "este_mes": total_este_mes,
            "mes_anterior": total_mes_ant,
            "cambio_pct": cambio_pct,
            "tickets_este_mes": tickets_este_mes,
            "tickets_mes_ant": tickets_mes_ant,
        },
        "proyeccion": {
            "proyeccion_mes": proyeccion_mes,
            "dias_transcurridos": dias_transcurridos,
            "dias_del_mes": dias_del_mes,
        },
        "utilidad": {
            "ingresos": total_este_mes,
            "costo_ventas": float(costo_ventas),
            "utilidad_bruta": float(utilidad_bruta),
            "gastos_fijos": float(total_gastos_fijos),
            "utilidad_neta": float(utilidad_neta),
        },
        "meses": meses,
        "clientes_vip": clientes_vip,
    }


# ─── Punto de equilibrio ─────────────────────────────────────────

def punto_de_equilibrio(db: Session, dias: int = 30) -> dict:
    """
    Calcula punto de equilibrio (break-even) de la panadería.
    Costos fijos / (1 - costos variables / ingresos) = PE en pesos.
    """
    from datetime import timedelta
    from app.models.inventario import Producto
    from app.models.gasto_fijo import GastoFijo

    hoy = date.today()
    inicio = datetime.combine(hoy - timedelta(days=dias - 1), datetime.min.time())
    fin = datetime.combine(hoy, datetime.max.time())

    # Ingresos del periodo
    ventas = db.query(Venta).filter(
        and_(Venta.estado == EstadoVenta.COMPLETADA,
             Venta.fecha >= inicio, Venta.fecha <= fin)
    ).all()
    ingresos = sum(float(v.total or 0) for v in ventas)

    # Costos variables (materia prima consumida en ventas)
    costo_variable = 0.0
    for v in ventas:
        for d in v.detalles:
            prod = db.query(Producto).filter(Producto.id == d.producto_id).first()
            if prod and prod.costo_produccion:
                costo_variable += float(d.cantidad * prod.costo_produccion)

    # Costos fijos mensuales
    gastos = db.query(GastoFijo).filter(GastoFijo.activo.is_(True)).all()
    costos_fijos_mensual = 0.0
    for g in gastos:
        if g.periodicidad == "quincenal":
            costos_fijos_mensual += float(g.monto) * 2
        elif g.periodicidad == "semanal":
            costos_fijos_mensual += float(g.monto) * 4.33
        else:
            costos_fijos_mensual += float(g.monto)

    # Nómina mensual
    from app.models.empleado import Empleado
    empleados = db.query(Empleado).filter(Empleado.activo.is_(True)).all()
    nomina_mensual = sum(float(e.salario_base or 0) for e in empleados)
    costos_fijos_mensual += nomina_mensual

    # Prorrateo al periodo
    costos_fijos_periodo = costos_fijos_mensual * (dias / 30)

    # Margen de contribución
    margen_contribucion_pct = ((ingresos - costo_variable) / ingresos * 100) if ingresos > 0 else 0

    # Punto de equilibrio en pesos
    pe_pesos = costos_fijos_periodo / (1 - costo_variable / ingresos) if ingresos > costo_variable else 0
    pe_diario = pe_pesos / dias if dias > 0 else 0

    # Ticket promedio
    num_ventas = len(ventas)
    ticket_promedio = ingresos / num_ventas if num_ventas > 0 else 0

    # PE en unidades (tickets)
    pe_unidades = pe_pesos / ticket_promedio if ticket_promedio > 0 else 0

    # Situación actual
    excedente = ingresos - pe_pesos
    pct_sobre_pe = (excedente / pe_pesos * 100) if pe_pesos > 0 else 0

    return {
        "dias_analizados": dias,
        "ingresos": round(ingresos, 2),
        "costo_variable": round(costo_variable, 2),
        "costos_fijos_periodo": round(costos_fijos_periodo, 2),
        "costos_fijos_mensuales": round(costos_fijos_mensual, 2),
        "nomina_mensual": round(nomina_mensual, 2),
        "margen_contribucion_pct": round(margen_contribucion_pct, 1),
        "punto_equilibrio_pesos": round(pe_pesos, 2),
        "punto_equilibrio_diario": round(pe_diario, 2),
        "punto_equilibrio_unidades": round(pe_unidades, 0),
        "ticket_promedio": round(ticket_promedio, 2),
        "excedente_sobre_pe": round(excedente, 2),
        "pct_sobre_pe": round(pct_sobre_pe, 1),
        "es_rentable": excedente > 0,
        "numero_ventas": num_ventas,
    }


def flujo_efectivo_proyectado(db: Session, meses: int = 3) -> dict:
    """
    Proyección de flujo de efectivo a N meses basado en tendencias históricas.
    """
    from datetime import timedelta
    from app.models.gasto_fijo import GastoFijo
    from app.models.empleado import Empleado

    hoy = date.today()

    # Calcular ingresos promedio mensuales de últimos 3 meses
    ingresos_mensuales = []
    for i in range(3):
        mes_fin = hoy.replace(day=1) - timedelta(days=1) if i == 0 else (hoy.replace(day=1) - timedelta(days=30 * i))
        mes_inicio = mes_fin.replace(day=1)
        inicio_dt = datetime.combine(mes_inicio, datetime.min.time())
        fin_dt = datetime.combine(mes_fin, datetime.max.time())
        total = db.query(func.coalesce(func.sum(Venta.total), 0)).filter(
            and_(Venta.estado == EstadoVenta.COMPLETADA,
                 Venta.fecha >= inicio_dt, Venta.fecha <= fin_dt)
        ).scalar()
        ingresos_mensuales.append(float(total))

    ingreso_promedio = sum(ingresos_mensuales) / len(ingresos_mensuales) if ingresos_mensuales else 0

    # Gastos fijos mensuales
    gastos = db.query(GastoFijo).filter(GastoFijo.activo.is_(True)).all()
    gastos_fijos_mes = 0.0
    desglose_gastos = {}
    for g in gastos:
        if g.periodicidad == "quincenal":
            monto = float(g.monto) * 2
        elif g.periodicidad == "semanal":
            monto = float(g.monto) * 4.33
        else:
            monto = float(g.monto)
        gastos_fijos_mes += monto
        desglose_gastos[g.concepto] = round(monto, 2)

    # Nómina
    empleados = db.query(Empleado).filter(Empleado.activo.is_(True)).all()
    nomina = sum(float(e.salario_base or 0) for e in empleados)

    total_egresos = gastos_fijos_mes + nomina

    # Proyección
    proyeccion = []
    saldo_acumulado = 0.0
    for i in range(1, meses + 1):
        mes_futuro = hoy.month + i
        anio = hoy.year + (mes_futuro - 1) // 12
        mes = ((mes_futuro - 1) % 12) + 1
        flujo_neto = ingreso_promedio - total_egresos
        saldo_acumulado += flujo_neto
        proyeccion.append({
            "mes": f"{anio}-{mes:02d}",
            "ingresos_estimados": round(ingreso_promedio, 2),
            "egresos_estimados": round(total_egresos, 2),
            "flujo_neto": round(flujo_neto, 2),
            "saldo_acumulado": round(saldo_acumulado, 2),
        })

    return {
        "meses_proyectados": meses,
        "ingreso_promedio_mensual": round(ingreso_promedio, 2),
        "ingresos_ultimos_3_meses": [round(x, 2) for x in ingresos_mensuales],
        "gastos_fijos_mensuales": round(gastos_fijos_mes, 2),
        "nomina_mensual": round(nomina, 2),
        "total_egresos_mensuales": round(total_egresos, 2),
        "desglose_gastos": desglose_gastos,
        "proyeccion": proyeccion,
    }


# ─── Comparativo anual (Year-over-Year) ──────────────────────────

def comparativo_anual(db: Session, anio: int) -> list[dict]:
    """
    Compara ventas mes a mes del año indicado vs. el año anterior.
    Retorna lista de {mes, ventas_actual, ventas_anterior, cambio_pct}.
    """
    resultados = []
    for mes in range(1, 13):
        # Ventas del año actual
        ventas_actual = db.query(
            func.coalesce(func.sum(Venta.total), 0)
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            extract("year", Venta.fecha) == anio,
            extract("month", Venta.fecha) == mes,
        ).scalar()

        # Ventas del año anterior
        ventas_anterior = db.query(
            func.coalesce(func.sum(Venta.total), 0)
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            extract("year", Venta.fecha) == anio - 1,
            extract("month", Venta.fecha) == mes,
        ).scalar()

        ventas_actual = float(ventas_actual or 0)
        ventas_anterior = float(ventas_anterior or 0)

        if ventas_anterior > 0:
            cambio_pct = round(
                ((ventas_actual - ventas_anterior) / ventas_anterior) * 100, 2
            )
        elif ventas_actual > 0:
            cambio_pct = 100.0
        else:
            cambio_pct = 0.0

        resultados.append({
            "mes": mes,
            "ventas_actual": round(ventas_actual, 2),
            "ventas_anterior": round(ventas_anterior, 2),
            "cambio_pct": cambio_pct,
        })

    return resultados


# ─── Análisis de estacionalidad ──────────────────────────────────

def analisis_estacionalidad(db: Session) -> dict:
    """
    Analiza patrones estacionales de ventas históricas.
    Identifica meses y fechas pico (Día de Muertos, Navidad,
    Día de las Madres, San Valentín, etc.)
    """
    # --- Ventas promedio por mes (todos los años) ---
    ventas_por_mes = []
    for mes in range(1, 13):
        total = db.query(
            func.coalesce(func.sum(Venta.total), 0)
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            extract("month", Venta.fecha) == mes,
        ).scalar()

        conteo = db.query(
            func.count(Venta.id)
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            extract("month", Venta.fecha) == mes,
        ).scalar()

        # Número de años distintos con ventas en este mes
        anios_distintos = db.query(
            func.count(func.distinct(extract("year", Venta.fecha)))
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            extract("month", Venta.fecha) == mes,
        ).scalar() or 1

        promedio_mensual = float(total or 0) / max(anios_distintos, 1)
        ventas_por_mes.append({
            "mes": mes,
            "total_historico": round(float(total or 0), 2),
            "promedio_anual": round(promedio_mensual, 2),
            "transacciones_totales": conteo or 0,
        })

    # Promedio global para calcular índice estacional
    promedio_global = sum(m["promedio_anual"] for m in ventas_por_mes) / 12 if ventas_por_mes else 1
    for m in ventas_por_mes:
        m["indice_estacional"] = round(
            m["promedio_anual"] / promedio_global, 2
        ) if promedio_global > 0 else 0.0

    # --- Fechas especiales mexicanas ---
    fechas_especiales = [
        {"nombre": "San Valentín", "mes": 2, "dia_inicio": 10, "dia_fin": 14},
        {"nombre": "Día de las Madres", "mes": 5, "dia_inicio": 7, "dia_fin": 10},
        {"nombre": "Día del Padre", "mes": 6, "dia_inicio": 15, "dia_fin": 20},
        {"nombre": "Independencia", "mes": 9, "dia_inicio": 13, "dia_fin": 16},
        {"nombre": "Día de Muertos", "mes": 10, "dia_inicio": 28, "dia_fin": 31},
        {"nombre": "Día de Muertos", "mes": 11, "dia_inicio": 1, "dia_fin": 2},
        {"nombre": "Navidad", "mes": 12, "dia_inicio": 20, "dia_fin": 25},
        {"nombre": "Año Nuevo", "mes": 12, "dia_inicio": 28, "dia_fin": 31},
    ]

    picos_festivos = []
    for evento in fechas_especiales:
        total_evento = db.query(
            func.coalesce(func.sum(Venta.total), 0)
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            extract("month", Venta.fecha) == evento["mes"],
            extract("day", Venta.fecha) >= evento["dia_inicio"],
            extract("day", Venta.fecha) <= evento["dia_fin"],
        ).scalar()

        conteo_evento = db.query(
            func.count(Venta.id)
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            extract("month", Venta.fecha) == evento["mes"],
            extract("day", Venta.fecha) >= evento["dia_inicio"],
            extract("day", Venta.fecha) <= evento["dia_fin"],
        ).scalar()

        if float(total_evento or 0) > 0:
            picos_festivos.append({
                "evento": evento["nombre"],
                "periodo": f"{evento['dia_inicio']}-{evento['dia_fin']}/{evento['mes']:02d}",
                "ventas_totales": round(float(total_evento), 2),
                "transacciones": conteo_evento or 0,
            })

    # Ordenar picos por ventas descendente
    picos_festivos.sort(key=lambda x: x["ventas_totales"], reverse=True)

    # --- Día de la semana más fuerte ---
    ventas_por_dia_semana = []
    # SQLite: strftime('%w', fecha) -> 0=domingo, ..., 6=sábado
    nombres_dia = {0: "Domingo", 1: "Lunes", 2: "Martes", 3: "Miércoles",
                   4: "Jueves", 5: "Viernes", 6: "Sábado"}
    for dow in range(7):
        total_dow = db.query(
            func.coalesce(func.sum(Venta.total), 0)
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            db_extract_dow(Venta.fecha) == str(dow),
        ).scalar()

        conteo_dow = db.query(
            func.count(Venta.id)
        ).filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            db_extract_dow(Venta.fecha) == str(dow),
        ).scalar()

        ventas_por_dia_semana.append({
            "dia": nombres_dia[dow],
            "dia_numero": dow,
            "ventas_totales": round(float(total_dow or 0), 2),
            "transacciones": conteo_dow or 0,
        })

    # Mejor y peor mes
    mejor_mes = max(ventas_por_mes, key=lambda x: x["promedio_anual"]) if ventas_por_mes else None
    peor_mes = min(ventas_por_mes, key=lambda x: x["promedio_anual"]) if ventas_por_mes else None

    nombres_mes = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
    }

    return {
        "ventas_por_mes": ventas_por_mes,
        "picos_festivos": picos_festivos,
        "ventas_por_dia_semana": ventas_por_dia_semana,
        "mejor_mes": {
            "mes": nombres_mes.get(mejor_mes["mes"], ""),
            "promedio_anual": mejor_mes["promedio_anual"],
        } if mejor_mes else None,
        "peor_mes": {
            "mes": nombres_mes.get(peor_mes["mes"], ""),
            "promedio_anual": peor_mes["promedio_anual"],
        } if peor_mes else None,
    }


# ─── Alertas consolidadas (notificaciones) ───────────────────────

def alertas_consolidadas(db: Session) -> list[dict]:
    """Todas las alertas activas del sistema para notificaciones."""
    from datetime import timedelta
    from app.models.inventario import Producto, LoteIngrediente
    from app.models.pedido import Pedido

    hoy = date.today()
    alertas = []

    # 1. Stock bajo / agotado
    productos = db.query(Producto).filter(
        Producto.activo.is_(True),
        Producto.stock_minimo > 0,
    ).all()
    for p in productos:
        if p.stock_actual <= 0:
            alertas.append({
                "tipo": "stock_agotado",
                "prioridad": "alta",
                "titulo": f"Agotado: {p.nombre}",
                "mensaje": f"{p.nombre} tiene stock 0. Reponer urgente.",
                "icono": "🚨",
            })
        elif p.stock_actual <= p.stock_minimo:
            alertas.append({
                "tipo": "stock_bajo",
                "prioridad": "media",
                "titulo": f"Stock bajo: {p.nombre}",
                "mensaje": f"{p.nombre}: {float(p.stock_actual)} pzas (mín: {float(p.stock_minimo)})",
                "icono": "⚠️",
            })

    # 2. Lotes por caducar (7 días)
    limite = hoy + timedelta(days=7)
    from app.models.inventario import Ingrediente
    lotes = db.query(LoteIngrediente).filter(
        and_(
            LoteIngrediente.fecha_caducidad.isnot(None),
            LoteIngrediente.fecha_caducidad <= limite,
            LoteIngrediente.cantidad_disponible > 0,
        )
    ).all()
    for lote in lotes:
        ing = db.query(Ingrediente).filter(Ingrediente.id == lote.ingrediente_id).first()
        dias_rest = (lote.fecha_caducidad - hoy).days
        vencido = dias_rest < 0
        alertas.append({
            "tipo": "caducidad",
            "prioridad": "alta" if vencido else "media",
            "titulo": f"{'Vencido' if vencido else 'Por caducar'}: {ing.nombre if ing else 'Ingrediente'}",
            "mensaje": f"Lote {lote.numero_lote}: {'venció hace ' + str(abs(dias_rest)) if vencido else str(dias_rest) + ' días restantes'}. Cant: {float(lote.cantidad_disponible)}",
            "icono": "🔴" if vencido else "🟡",
        })

    # 3. Pedidos pendientes para hoy/mañana
    manana = hoy + timedelta(days=1)
    pedidos = db.query(Pedido).filter(
        and_(
            Pedido.estado.notin_(["entregado", "cancelado"]),
            Pedido.fecha_entrega.isnot(None),
            Pedido.fecha_entrega <= manana,
        )
    ).all()
    for p in pedidos:
        es_hoy = p.fecha_entrega == hoy if p.fecha_entrega else False
        alertas.append({
            "tipo": "pedido",
            "prioridad": "alta" if es_hoy else "media",
            "titulo": f"Pedido {p.folio}: {p.cliente_nombre}",
            "mensaje": f"Entrega {'HOY' if es_hoy else 'mañana'}" + (f" a las {p.hora_entrega}" if p.hora_entrega else "") + f". Estado: {p.estado.value}",
            "icono": "📦",
        })

    # Sort by priority
    prioridad_orden = {"alta": 0, "media": 1, "baja": 2}
    alertas.sort(key=lambda x: prioridad_orden.get(x["prioridad"], 9))

    return alertas
