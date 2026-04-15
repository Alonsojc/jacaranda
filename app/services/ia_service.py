"""
Servicio de IA: pronóstico de demanda y pricing dinámico.
Algoritmos estadísticos sin dependencias externas de ML.
"""

from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.core.db_compat import db_cast_date
from app.models.venta import Venta, DetalleVenta, EstadoVenta
from app.models.inventario import Producto, HistorialPrecio

ZERO = Decimal("0")


# ─── Pronóstico de demanda ────────────────────────────────────────

def pronostico_demanda(
    db: Session,
    dias_futuro: int = 7,
    semanas_historico: int = 8,
) -> list[dict]:
    """
    Pronóstico de demanda por producto para los próximos N días.
    Usa media móvil ponderada por día de semana + detección de tendencia.
    """
    hoy = date.today()
    inicio = hoy - timedelta(weeks=semanas_historico)
    inicio_dt = datetime.combine(inicio, datetime.min.time(), tzinfo=timezone.utc)

    # Get all completed sale details with date info
    rows = db.query(
        DetalleVenta.producto_id,
        db_cast_date(Venta.fecha).label("dia"),
        func.sum(DetalleVenta.cantidad).label("qty"),
    ).join(Venta, Venta.id == DetalleVenta.venta_id).filter(
        and_(Venta.estado == EstadoVenta.COMPLETADA, Venta.fecha >= inicio_dt)
    ).group_by(
        DetalleVenta.producto_id, db_cast_date(Venta.fecha)
    ).all()

    # Organize: {producto_id: {date_str: qty}}
    ventas_por_prod = defaultdict(dict)
    for pid, dia, qty in rows:
        d = dia if isinstance(dia, date) else date.fromisoformat(str(dia))
        ventas_por_prod[pid][d] = float(qty)

    # Load products
    productos = {p.id: p for p in db.query(Producto).filter(Producto.activo.is_(True)).all()}

    resultados = []
    for pid, hist in ventas_por_prod.items():
        prod = productos.get(pid)
        if not prod:
            continue

        # Build time series by day-of-week
        dow_data = defaultdict(list)  # {0-6: [(week_num, qty)]}
        for d, qty in sorted(hist.items()):
            week_num = (d - inicio).days // 7
            dow_data[d.weekday()].append((week_num, qty))

        # Generate forecast for each future day
        predicciones = []
        for delta in range(1, dias_futuro + 1):
            dia_futuro = hoy + timedelta(days=delta)
            dow = dia_futuro.weekday()
            series = dow_data.get(dow, [])

            if not series:
                # No data for this day-of-week, use overall average
                all_vals = list(hist.values())
                pred = sum(all_vals) / max(len(all_vals), 1) if all_vals else 0
                confianza = 20
            else:
                pred, confianza = _media_ponderada_con_tendencia(series, semanas_historico)

            predicciones.append({
                "fecha": dia_futuro.isoformat(),
                "dia_semana": _nombre_dia(dow),
                "cantidad": round(max(pred, 0), 1),
                "confianza": min(confianza, 99),
            })

        # Summary stats
        total_historico = sum(hist.values())
        dias_con_venta = len(hist)
        promedio_diario = total_historico / max(dias_con_venta, 1)

        # Trend: compare last 2 weeks vs previous 2 weeks
        hace_2sem = hoy - timedelta(weeks=2)
        hace_4sem = hoy - timedelta(weeks=4)
        reciente = sum(v for d, v in hist.items() if d >= hace_2sem)
        anterior = sum(v for d, v in hist.items() if hace_4sem <= d < hace_2sem)
        tendencia = 0.0
        if anterior > 0:
            tendencia = round((reciente - anterior) / anterior * 100, 1)

        resultados.append({
            "producto_id": pid,
            "nombre": prod.nombre,
            "stock_actual": float(prod.stock_actual or 0),
            "promedio_diario": round(promedio_diario, 1),
            "tendencia_pct": tendencia,
            "predicciones": predicciones,
        })

    # Sort by average daily sales descending
    resultados.sort(key=lambda x: x["promedio_diario"], reverse=True)
    return resultados


def pronostico_produccion_ia(db: Session) -> list[dict]:
    """
    Sugerencia de producción para mañana basada en pronóstico IA.
    Retorna lista ordenada por prioridad de hornear.
    """
    forecast = pronostico_demanda(db, dias_futuro=1, semanas_historico=8)
    productos = {p.id: p for p in db.query(Producto).filter(Producto.activo.is_(True)).all()}

    sugerencias = []
    for item in forecast:
        pred_manana = item["predicciones"][0] if item["predicciones"] else None
        if not pred_manana:
            continue

        prod = productos.get(item["producto_id"])
        if not prod:
            continue

        demanda = pred_manana["cantidad"]
        stock = float(prod.stock_actual or 0)
        # Apply 15% safety margin
        necesario = demanda * 1.15
        hornear = max(round(necesario - stock), 0)

        if hornear > 0 or demanda > 0:
            sugerencias.append({
                "producto_id": item["producto_id"],
                "nombre": item["nombre"],
                "demanda_estimada": round(demanda, 1),
                "stock_actual": round(stock, 1),
                "sugerido_hornear": hornear,
                "confianza": pred_manana["confianza"],
                "tendencia_pct": item["tendencia_pct"],
                "dia": pred_manana["dia_semana"],
                "prioridad": "alta" if hornear > 0 and stock < demanda * 0.5 else
                             "media" if hornear > 0 else "baja",
            })

    # Sort: alta first, then by hornear descending
    orden = {"alta": 0, "media": 1, "baja": 2}
    sugerencias.sort(key=lambda x: (orden.get(x["prioridad"], 3), -x["sugerido_hornear"]))
    return sugerencias


def _media_ponderada_con_tendencia(series: list[tuple], total_semanas: int) -> tuple[float, int]:
    """
    Calcula predicción con media ponderada exponencial + ajuste de tendencia.
    series: [(week_num, qty)] ordenado por week_num.
    Returns: (prediccion, confianza %).
    """
    if not series:
        return 0.0, 10

    # Weights: more recent weeks get more weight (exponential decay)
    valores = []
    pesos = []
    for week_num, qty in series:
        peso = 2 ** (week_num / max(total_semanas, 1))  # exponential growth
        valores.append(qty)
        pesos.append(peso)

    # Weighted average
    total_peso = sum(pesos)
    if total_peso == 0:
        return sum(valores) / len(valores), 30

    media_ponderada = sum(v * w for v, w in zip(valores, pesos)) / total_peso

    # Trend adjustment using linear regression on the series
    n = len(valores)
    if n >= 3:
        # Simple linear regression: y = a + b*x
        x_mean = sum(range(n)) / n
        y_mean = sum(valores) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(valores))
        den = sum((i - x_mean) ** 2 for i in range(n))
        if den > 0:
            slope = num / den
            # Project one step ahead
            trend_adj = slope * 0.5  # dampened trend
            media_ponderada += trend_adj

    # Confidence: based on data points and consistency
    if n >= 6:
        confianza = 85
    elif n >= 4:
        confianza = 70
    elif n >= 2:
        confianza = 50
    else:
        confianza = 30

    # Reduce confidence if high variance
    if n >= 2:
        variance = sum((v - sum(valores) / n) ** 2 for v in valores) / n
        cv = (variance ** 0.5) / max(sum(valores) / n, 0.01)  # coeff of variation
        if cv > 0.5:
            confianza = max(confianza - 20, 15)
        elif cv > 0.3:
            confianza = max(confianza - 10, 20)

    return max(media_ponderada, 0), confianza


# ─── Pricing dinámico ─────────────────────────────────────────────

def analisis_pricing(db: Session, dias: int = 60) -> list[dict]:
    """
    Análisis de pricing: elasticidad, sugerencias de precio, productos sin rotación.
    """
    hoy = date.today()
    inicio = hoy - timedelta(days=dias)
    inicio_dt = datetime.combine(inicio, datetime.min.time(), tzinfo=timezone.utc)

    productos = db.query(Producto).filter(Producto.activo.is_(True)).all()

    resultados = []
    for prod in productos:
        precio = float(prod.precio_unitario or 0)
        costo = float(prod.costo_produccion or 0)
        if precio <= 0:
            continue

        margen_pct = round((precio - costo) / precio * 100, 1) if precio > 0 else 0

        # Sales in period
        ventas = db.query(
            func.sum(DetalleVenta.cantidad).label("qty"),
            func.sum(DetalleVenta.subtotal).label("ingreso"),
            func.count(DetalleVenta.id).label("transacciones"),
        ).join(Venta, Venta.id == DetalleVenta.venta_id).filter(
            and_(
                DetalleVenta.producto_id == prod.id,
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= inicio_dt,
            )
        ).first()

        qty_vendida = float(ventas.qty or 0)
        ingreso = float(ventas.ingreso or 0)
        transacciones = int(ventas.transacciones or 0)

        # Days since last sale
        ultima_venta = db.query(func.max(Venta.fecha)).join(
            DetalleVenta, DetalleVenta.venta_id == Venta.id
        ).filter(
            and_(
                DetalleVenta.producto_id == prod.id,
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        ).scalar()

        dias_sin_venta = (hoy - ultima_venta.date()).days if ultima_venta else 999

        # Price elasticity from price history
        elasticidad = _calcular_elasticidad(db, prod.id, inicio_dt)

        # Rotation speed (units per day)
        rotacion = qty_vendida / max(dias, 1)

        # Pricing suggestion
        sugerencia = _sugerir_precio(
            precio, costo, margen_pct, elasticidad,
            rotacion, dias_sin_venta, float(prod.stock_actual or 0),
        )

        resultados.append({
            "producto_id": prod.id,
            "nombre": prod.nombre,
            "precio_actual": precio,
            "costo": costo,
            "margen_pct": margen_pct,
            "qty_vendida": round(qty_vendida, 1),
            "ingreso_periodo": round(ingreso, 2),
            "transacciones": transacciones,
            "rotacion_diaria": round(rotacion, 2),
            "dias_sin_venta": dias_sin_venta,
            "elasticidad": elasticidad,
            "stock_actual": float(prod.stock_actual or 0),
            "sugerencia": sugerencia,
        })

    # Sort by suggestion priority
    prioridad = {"subir": 0, "bajar": 1, "descuento": 2, "mantener": 3}
    resultados.sort(key=lambda x: (
        prioridad.get(x["sugerencia"]["accion"], 4),
        -abs(x["sugerencia"].get("impacto_mensual", 0)),
    ))
    return resultados


def _calcular_elasticidad(db: Session, producto_id: int, desde: datetime) -> dict | None:
    """
    Calcula elasticidad de precio: % cambio demanda / % cambio precio.
    Compara ventas antes vs después de cada cambio de precio.
    """
    cambios = db.query(HistorialPrecio).filter(
        and_(
            HistorialPrecio.producto_id == producto_id,
            HistorialPrecio.fecha >= desde,
        )
    ).order_by(HistorialPrecio.fecha).all()

    if not cambios:
        return None

    elasticidades = []
    for cambio in cambios:
        if not cambio.precio_anterior or not cambio.precio_nuevo:
            continue
        p_ant = float(cambio.precio_anterior)
        p_new = float(cambio.precio_nuevo)
        if p_ant == 0:
            continue

        pct_precio = (p_new - p_ant) / p_ant

        # Compare sales 14 days before vs 14 days after
        fecha_cambio = cambio.fecha
        antes_inicio = fecha_cambio - timedelta(days=14)
        despues_fin = fecha_cambio + timedelta(days=14)

        qty_antes = db.query(func.coalesce(func.sum(DetalleVenta.cantidad), 0)).join(
            Venta, Venta.id == DetalleVenta.venta_id
        ).filter(
            and_(
                DetalleVenta.producto_id == producto_id,
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= antes_inicio,
                Venta.fecha < fecha_cambio,
            )
        ).scalar()

        qty_despues = db.query(func.coalesce(func.sum(DetalleVenta.cantidad), 0)).join(
            Venta, Venta.id == DetalleVenta.venta_id
        ).filter(
            and_(
                DetalleVenta.producto_id == producto_id,
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= fecha_cambio,
                Venta.fecha <= despues_fin,
            )
        ).scalar()

        qty_a = float(qty_antes)
        qty_d = float(qty_despues)

        if qty_a > 0 and abs(pct_precio) > 0.01:
            pct_demanda = (qty_d - qty_a) / qty_a
            elast = pct_demanda / pct_precio
            elasticidades.append(round(elast, 2))

    if not elasticidades:
        return None

    promedio = sum(elasticidades) / len(elasticidades)
    return {
        "valor": round(promedio, 2),
        "interpretacion": (
            "inelástico" if abs(promedio) < 1 else "elástico"
        ),
        "muestras": len(elasticidades),
    }


def _sugerir_precio(
    precio: float, costo: float, margen_pct: float,
    elasticidad: dict | None, rotacion: float,
    dias_sin_venta: int, stock: float,
) -> dict:
    """Genera sugerencia de pricing basada en múltiples factores."""
    margen_minimo = 25.0  # % minimum margin

    # Case 1: Product hasn't sold in a while with stock
    if dias_sin_venta > 14 and stock > 0:
        descuento = min(30, max(10, dias_sin_venta // 7 * 5))
        nuevo = round(max(precio * (1 - descuento / 100), costo * 1.1), 2)
        return {
            "accion": "descuento",
            "precio_sugerido": nuevo,
            "razon": f"{dias_sin_venta} días sin venta, {int(stock)} en stock",
            "descuento_pct": descuento,
            "impacto_mensual": round(-(precio - nuevo) * stock * 0.5, 2),
        }

    # Case 2: Inelastic demand + good margin → can raise price
    if elasticidad and abs(elasticidad["valor"]) < 0.8 and margen_pct >= margen_minimo:
        incremento = 5 if abs(elasticidad["valor"]) < 0.5 else 3
        nuevo = round(precio * (1 + incremento / 100), 2)
        impacto = round(rotacion * 30 * (nuevo - precio), 2)
        return {
            "accion": "subir",
            "precio_sugerido": nuevo,
            "razon": f"Demanda inelástica ({elasticidad['valor']}), margen {margen_pct}%",
            "incremento_pct": incremento,
            "impacto_mensual": impacto,
        }

    # Case 3: Low margin → should raise
    if margen_pct < margen_minimo and margen_pct > 0:
        nuevo = round(costo * (1 + margen_minimo / 100), 2)
        if nuevo > precio:
            return {
                "accion": "subir",
                "precio_sugerido": nuevo,
                "razon": f"Margen bajo ({margen_pct}%), mínimo recomendado {margen_minimo}%",
                "incremento_pct": round((nuevo - precio) / precio * 100, 1),
                "impacto_mensual": round(rotacion * 30 * (nuevo - precio), 2),
            }

    # Case 4: Elastic demand + slow rotation → lower price to move
    if elasticidad and elasticidad["valor"] < -1.5 and rotacion < 1:
        descuento = 10
        nuevo = round(max(precio * 0.9, costo * 1.15), 2)
        return {
            "accion": "bajar",
            "precio_sugerido": nuevo,
            "razon": f"Demanda elástica ({elasticidad['valor']}), rotación baja ({rotacion}/día)",
            "descuento_pct": descuento,
            "impacto_mensual": round(rotacion * 1.5 * 30 * (nuevo - costo) - rotacion * 30 * (precio - costo), 2),
        }

    # Default: price is optimal
    return {
        "accion": "mantener",
        "precio_sugerido": precio,
        "razon": f"Precio óptimo. Margen {margen_pct}%, rotación {rotacion}/día",
        "impacto_mensual": 0,
    }


# ─── Precisión del modelo ─────────────────────────────────────────

def precision_modelo(db: Session, dias_atras: int = 14) -> dict:
    """
    Evalúa precisión del pronóstico comparando predicciones pasadas con ventas reales.
    Simula lo que hubiera predicho hace N días y compara con lo que pasó.
    """
    hoy = date.today()
    errores = []
    comparaciones = []

    # For each of the last N days, simulate what we'd have predicted
    for delta in range(1, min(dias_atras + 1, 15)):
        dia_evaluado = hoy - timedelta(days=delta)
        dia_anterior = dia_evaluado - timedelta(days=1)

        # What we would have predicted (using data up to dia_anterior)
        predicho = _predecir_dia_historico(db, dia_evaluado, semanas=6)

        # What actually happened
        inicio_dt = datetime.combine(dia_evaluado, datetime.min.time(), tzinfo=timezone.utc)
        fin_dt = datetime.combine(dia_evaluado, datetime.max.time(), tzinfo=timezone.utc)

        real = db.query(
            DetalleVenta.producto_id,
            func.sum(DetalleVenta.cantidad).label("qty"),
        ).join(Venta, Venta.id == DetalleVenta.venta_id).filter(
            and_(
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= inicio_dt,
                Venta.fecha <= fin_dt,
            )
        ).group_by(DetalleVenta.producto_id).all()

        real_map = {pid: float(qty) for pid, qty in real}

        # Compare
        for pid, pred_qty in predicho.items():
            real_qty = real_map.get(pid, 0)
            if pred_qty > 0 or real_qty > 0:
                error = abs(pred_qty - real_qty)
                base = max(pred_qty, real_qty, 1)
                error_pct = error / base * 100
                errores.append(error_pct)
                comparaciones.append({
                    "fecha": dia_evaluado.isoformat(),
                    "producto_id": pid,
                    "predicho": round(pred_qty, 1),
                    "real": round(real_qty, 1),
                    "error_pct": round(error_pct, 1),
                })

    if not errores:
        return {
            "precision_promedio": 0,
            "mape": 0,
            "muestras": 0,
            "comparaciones": [],
            "calificacion": "sin datos",
        }

    mape = sum(errores) / len(errores)
    precision = max(100 - mape, 0)

    if precision >= 80:
        calif = "excelente"
    elif precision >= 65:
        calif = "buena"
    elif precision >= 50:
        calif = "aceptable"
    else:
        calif = "en entrenamiento"

    # Top 20 most recent comparisons
    comparaciones.sort(key=lambda x: (x["fecha"], -x["error_pct"]), reverse=True)

    return {
        "precision_promedio": round(precision, 1),
        "mape": round(mape, 1),
        "muestras": len(errores),
        "dias_evaluados": min(dias_atras, 14),
        "comparaciones": comparaciones[:20],
        "calificacion": calif,
    }


def _predecir_dia_historico(
    db: Session, dia: date, semanas: int = 6
) -> dict[int, float]:
    """Predice ventas para un día usando datos anteriores a ese día."""
    inicio = dia - timedelta(weeks=semanas)
    inicio_dt = datetime.combine(inicio, datetime.min.time(), tzinfo=timezone.utc)
    fin_dt = datetime.combine(dia - timedelta(days=1), datetime.max.time(), tzinfo=timezone.utc)

    rows = db.query(
        DetalleVenta.producto_id,
        db_cast_date(Venta.fecha).label("d"),
        func.sum(DetalleVenta.cantidad).label("qty"),
    ).join(Venta, Venta.id == DetalleVenta.venta_id).filter(
        and_(
            Venta.estado == EstadoVenta.COMPLETADA,
            Venta.fecha >= inicio_dt,
            Venta.fecha <= fin_dt,
        )
    ).group_by(DetalleVenta.producto_id, db_cast_date(Venta.fecha)).all()

    # Group by product and day-of-week matching target
    target_dow = dia.weekday()
    por_prod = defaultdict(list)
    for pid, d_raw, qty in rows:
        d = d_raw if isinstance(d_raw, date) else date.fromisoformat(str(d_raw))
        if d.weekday() == target_dow:
            week_num = (d - inicio).days // 7
            por_prod[pid].append((week_num, float(qty)))

    predicciones = {}
    for pid, series in por_prod.items():
        pred, _ = _media_ponderada_con_tendencia(series, semanas)
        predicciones[pid] = pred

    return predicciones


# ─── Dashboard IA ──────────────────────────────────────────────────

def dashboard_ia(db: Session) -> dict:
    """Dashboard consolidado de IA: resumen rápido."""
    # Production suggestions for tomorrow
    sugerencias = pronostico_produccion_ia(db)
    top_hornear = sugerencias[:5]

    # Pricing alerts
    pricing = analisis_pricing(db, dias=30)
    alertas_precio = [p for p in pricing if p["sugerencia"]["accion"] != "mantener"][:5]

    # Model accuracy
    precision = precision_modelo(db, dias_atras=7)

    # Products not selling
    sin_venta = [p for p in pricing if p["dias_sin_venta"] > 7 and p["stock_actual"] > 0]

    # Potential monthly impact from pricing changes
    impacto_total = sum(
        p["sugerencia"].get("impacto_mensual", 0)
        for p in pricing if p["sugerencia"]["accion"] in ("subir",)
    )

    return {
        "sugerencias_produccion": top_hornear,
        "alertas_pricing": alertas_precio,
        "precision_modelo": {
            "valor": precision["precision_promedio"],
            "calificacion": precision["calificacion"],
            "muestras": precision["muestras"],
        },
        "productos_sin_rotacion": len(sin_venta),
        "impacto_potencial_mensual": round(impacto_total, 2),
        "total_productos_analizados": len(pricing),
    }


# ─── Helpers ──────────────────────────────────────────────────────

def _nombre_dia(dow: int) -> str:
    return ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dow]
