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
