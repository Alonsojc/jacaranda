"""
Servicio de IA: pronóstico de demanda y pricing dinámico.
Algoritmos estadísticos sin dependencias externas de ML.
"""

from decimal import Decimal
from datetime import date, timedelta
from collections import defaultdict
from math import ceil
import re
import unicodedata
from sqlalchemy.orm import Session, load_only, joinedload
from sqlalchemy import func

from app.core.time_utils import operation_datetime, operation_period_bounds, operation_today
from app.models.venta import Venta, DetalleVenta, EstadoVenta
from app.models.inventario import Producto, HistorialPrecio, CategoriaProducto, CategoriaProductoEnum

ZERO = Decimal("0")


def _productos(db: Session) -> dict[int, Producto]:
    return {p.id: p for p in db.query(Producto).options(
        load_only(Producto.id, Producto.nombre, Producto.precio_unitario,
                  Producto.costo_produccion, Producto.stock_actual),
        joinedload(Producto.categoria).load_only(CategoriaProducto.tipo),
    ).filter(Producto.activo.is_(True)).all()}


def _ventas_diarias(db: Session, inicio: date, fin: date) -> dict:
    inicio_dt, fin_dt = operation_period_bounds(inicio, fin)
    rows = db.query(DetalleVenta.producto_id, Venta.fecha, DetalleVenta.cantidad).join(
        Venta, Venta.id == DetalleVenta.venta_id,
    ).filter(Venta.estado == EstadoVenta.COMPLETADA,
             Venta.fecha >= inicio_dt, Venta.fecha <= fin_dt).all()
    historial = defaultdict(lambda: defaultdict(float))
    for pid, fecha, cantidad in rows:
        historial[pid][operation_datetime(fecha).date()] += float(cantidad)
    return historial


def _series_diarias(hist: dict, inicio: date, fin: date) -> dict:
    """Include zero-sale days after the first observed sale, never before it."""
    series = defaultdict(list)
    observados = [dia for dia in hist if inicio <= dia <= fin]
    if not observados:
        return series
    dia = max(inicio, min(observados))
    while dia <= fin:
        series[dia.weekday()].append(((dia - inicio).days // 7, hist.get(dia, 0)))
        dia += timedelta(days=1)
    return series


def _es_horneable(prod: Producto) -> bool:
    if prod.categoria and prod.categoria.tipo in (
        CategoriaProductoEnum.BEBIDAS, CategoriaProductoEnum.OTROS,
    ):
        return False
    nombre = unicodedata.normalize("NFKD", prod.nombre).encode("ascii", "ignore").decode().lower()
    return not re.search(r"\b(velas?|chisperos?|toppers?)\b", nombre)


# ─── Pronóstico de demanda ────────────────────────────────────────

def pronostico_demanda(
    db: Session,
    dias_futuro: int = 7,
    semanas_historico: int = 8,
    *, historial: dict | None = None, productos: dict | None = None,
) -> list[dict]:
    """
    Pronóstico de demanda por producto para los próximos N días.
    Usa media móvil ponderada por día de semana + detección de tendencia.
    """
    hoy = operation_today()
    inicio = hoy - timedelta(weeks=semanas_historico)
    ayer = hoy - timedelta(days=1)
    ventas_por_prod = historial if historial is not None else _ventas_diarias(db, inicio, ayer)
    productos = productos if productos is not None else _productos(db)

    resultados = []
    for pid, hist in ventas_por_prod.items():
        hist = {d: qty for d, qty in hist.items() if inicio <= d <= ayer}
        prod = productos.get(pid)
        if not prod or not hist:
            continue

        # Build time series by day-of-week
        dow_data = _series_diarias(hist, inicio, ayer)

        # Generate forecast for each future day
        predicciones = []
        for delta in range(1, dias_futuro + 1):
            dia_futuro = hoy + timedelta(days=delta)
            dow = dia_futuro.weekday()
            series = dow_data.get(dow, [])

            if not series:
                # No data for this day-of-week, use overall average
                pred = sum(hist.values()) / max((hoy - min(hist)).days, 1)
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
        promedio_diario = total_historico / max((hoy - min(hist)).days, 1)

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
            "dias_con_venta": dias_con_venta,
            "horneable": _es_horneable(prod),
            "predicciones": predicciones,
        })

    # Sort by average daily sales descending
    resultados.sort(key=lambda x: x["promedio_diario"], reverse=True)
    return resultados


def pronostico_produccion_ia(db: Session, *, historial=None, productos=None) -> list[dict]:
    """
    Sugerencia de producción para mañana basada en pronóstico IA.
    Retorna lista ordenada por prioridad de hornear.
    """
    productos = productos if productos is not None else _productos(db)
    forecast = pronostico_demanda(db, dias_futuro=1, semanas_historico=8,
                                 historial=historial, productos=productos)

    sugerencias = []
    for item in forecast:
        pred_manana = item["predicciones"][0] if item["predicciones"] else None
        if not pred_manana:
            continue

        prod = productos.get(item["producto_id"])
        if not prod or not item["horneable"]:
            continue

        demanda = pred_manana["cantidad"]
        stock = float(prod.stock_actual or 0)
        # Apply 15% safety margin
        necesario = demanda * 1.15
        advertencias = []
        if stock < 0:
            advertencias.append("Stock negativo: revisar inventario; no se suma a la demanda")
        if item["dias_con_venta"] < 2:
            advertencias.append("Historial insuficiente: revisar antes de producir")
        hornear = max(ceil(necesario - max(stock, 0)), 0) if item["dias_con_venta"] >= 2 else 0

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
                "advertencias": advertencias,
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

    media_ponderada = sum(v * w for v, w in zip(valores, pesos, strict=False)) / total_peso

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

def analisis_pricing(db: Session, dias: int = 60, *, productos=None) -> list[dict]:
    """
    Análisis de pricing: elasticidad, sugerencias de precio, productos sin rotación.
    """
    hoy = operation_today()
    inicio = hoy - timedelta(days=dias)
    inicio_dt, fin_dt = operation_period_bounds(inicio, hoy - timedelta(days=1))

    productos = productos if productos is not None else _productos(db)
    ventas_periodo = {row.producto_id: row for row in db.query(
        DetalleVenta.producto_id,
        func.sum(DetalleVenta.cantidad).label("qty"),
        func.sum(DetalleVenta.subtotal).label("ingreso"),
        func.count(DetalleVenta.id).label("transacciones"),
    ).join(Venta, Venta.id == DetalleVenta.venta_id).filter(
        Venta.estado == EstadoVenta.COMPLETADA, Venta.fecha >= inicio_dt, Venta.fecha <= fin_dt,
    ).group_by(DetalleVenta.producto_id).all()}
    ultimas = dict(db.query(DetalleVenta.producto_id, func.max(Venta.fecha)).join(
        Venta, Venta.id == DetalleVenta.venta_id,
    ).filter(Venta.estado == EstadoVenta.COMPLETADA, Venta.fecha <= fin_dt).group_by(
        DetalleVenta.producto_id,
    ).all())
    cambios_por_prod = defaultdict(list)
    for cambio in db.query(HistorialPrecio).filter(
        HistorialPrecio.fecha >= inicio_dt, HistorialPrecio.fecha <= fin_dt,
    ).order_by(HistorialPrecio.fecha).all():
        cambios_por_prod[cambio.producto_id].append(cambio)
    historia_precios = _ventas_diarias(db, inicio - timedelta(days=14), hoy - timedelta(days=1)) if cambios_por_prod else {}

    resultados = []
    for prod in productos.values():
        precio = float(prod.precio_unitario or 0)
        costo = float(prod.costo_produccion or 0)
        if precio <= 0:
            continue

        margen_pct = round((precio - costo) / precio * 100, 1) if precio > 0 else 0

        # Sales in period
        ventas = ventas_periodo.get(prod.id)
        qty_vendida = float(ventas.qty or 0) if ventas else 0
        ingreso = float(ventas.ingreso or 0) if ventas else 0
        transacciones = int(ventas.transacciones or 0) if ventas else 0

        # Days since last sale
        ultima_venta = ultimas.get(prod.id)

        dias_sin_venta = (
            hoy - operation_datetime(ultima_venta).date()
        ).days if ultima_venta else 999

        # Price elasticity from price history
        elasticidad = _elasticidad_historica(cambios_por_prod[prod.id], historia_precios.get(prod.id, {}), hoy)

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


def _elasticidad_historica(cambios: list, historial: dict, hoy: date) -> dict | None:
    """Only compare complete, equally sized windows, excluding the change day."""
    elasticidades = []
    for cambio in cambios:
        if not cambio.precio_anterior or not cambio.precio_nuevo:
            continue
        p_ant = float(cambio.precio_anterior)
        p_new = float(cambio.precio_nuevo)
        if p_ant == 0:
            continue

        pct_precio = (p_new - p_ant) / p_ant

        fecha_cambio = operation_datetime(cambio.fecha).date()
        antes_inicio = fecha_cambio - timedelta(days=14)
        despues_fin = fecha_cambio + timedelta(days=14)
        if despues_fin >= hoy:
            continue
        qty_a = sum(q for d, q in historial.items() if antes_inicio <= d < fecha_cambio)
        qty_d = sum(q for d, q in historial.items() if fecha_cambio < d <= despues_fin)

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
    if costo <= 0 or costo >= precio:
        return {
            "accion": "revisar", "precio_sugerido": precio,
            "razon": "Revisar costo y precio del catalogo antes de sugerir cambios",
            "impacto_mensual": 0,
        }

    # Case 1: Product hasn't sold in a while with stock
    if dias_sin_venta > 14 and stock > 0:
        descuento = min(30, max(10, dias_sin_venta // 7 * 5))
        nuevo = round(max(precio * (1 - descuento / 100), costo * 1.1), 2)
        if nuevo >= precio:
            return {"accion": "mantener", "precio_sugerido": precio,
                    "razon": "Sin margen suficiente para descontar", "impacto_mensual": 0}
        return {
            "accion": "descuento",
            "precio_sugerido": nuevo,
            "razon": f"{dias_sin_venta} días sin venta, {int(stock)} en stock",
            "descuento_pct": round((precio - nuevo) / precio * 100, 1),
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
        nuevo = round(costo / (1 - margen_minimo / 100), 2)
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
        if nuevo >= precio:
            return {"accion": "mantener", "precio_sugerido": precio,
                    "razon": "Sin margen suficiente para bajar precio", "impacto_mensual": 0}
        return {
            "accion": "bajar",
            "precio_sugerido": nuevo,
            "razon": f"Demanda elástica ({elasticidad['valor']}), rotación baja ({rotacion}/día)",
            "descuento_pct": round((precio - nuevo) / precio * 100, 1),
            "impacto_mensual": round(rotacion * 1.5 * 30 * (nuevo - costo) - rotacion * 30 * (precio - costo), 2),
        }

    # Default: no change supported by these rules
    return {
        "accion": "mantener",
        "precio_sugerido": precio,
        "razon": f"Sin cambio sugerido. Margen {margen_pct}%, rotación {rotacion}/día",
        "impacto_mensual": 0,
    }


# ─── Precisión del modelo ─────────────────────────────────────────

def precision_modelo(db: Session, dias_atras: int = 14, *, historial=None) -> dict:
    """
    Evalúa precisión del pronóstico comparando predicciones pasadas con ventas reales.
    Simula lo que hubiera predicho hace N días y compara con lo que pasó.
    """
    hoy = operation_today()
    dias_atras = min(dias_atras, 30)
    historial = historial if historial is not None else _ventas_diarias(
        db, hoy - timedelta(days=dias_atras + 1, weeks=8), hoy - timedelta(days=1),
    )
    errores = []
    comparaciones = []

    # For each of the last N days, simulate what we'd have predicted
    for delta in range(1, dias_atras + 1):
        dia_evaluado = hoy - timedelta(days=delta)

        # Tomorrow's forecast is issued the prior day, using only closed days.
        predicho = _predecir_dia_historico(db, dia_evaluado, semanas=8, historial=historial)
        real_map = {pid: hist.get(dia_evaluado, 0) for pid, hist in historial.items()}

        # Compare
        for pid in predicho.keys() | real_map.keys():
            pred_qty = predicho.get(pid, 0)
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
            "error_normalizado_pct": 0,
            "metrica": "error absoluto / max(predicho, real, 1)",
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
        calif = "baja"

    # Top 20 most recent comparisons
    comparaciones.sort(key=lambda x: (x["fecha"], -x["error_pct"]), reverse=True)

    return {
        "precision_promedio": round(precision, 1),
        "mape": round(mape, 1),
        "error_normalizado_pct": round(mape, 1),
        "metrica": "error absoluto / max(predicho, real, 1)",
        "muestras": len(errores),
        "dias_evaluados": dias_atras,
        "comparaciones": comparaciones[:20],
        "calificacion": calif,
    }


def _predecir_dia_historico(
    db: Session, dia: date, semanas: int = 8, *, historial=None,
) -> dict[int, float]:
    """Replay the same closed-day cutoff as the forecast issued the prior day."""
    fecha_emision = dia - timedelta(days=1)
    inicio = fecha_emision - timedelta(weeks=semanas)
    ayer = fecha_emision - timedelta(days=1)
    historial = historial if historial is not None else _ventas_diarias(db, inicio, ayer)
    predicciones = {}
    for pid, hist in historial.items():
        hist = {d: q for d, q in hist.items() if inicio <= d <= ayer}
        if not hist:
            continue
        series = _series_diarias(hist, inicio, ayer).get(dia.weekday(), [])
        if series:
            pred, _ = _media_ponderada_con_tendencia(series, semanas)
        else:
            pred = sum(hist.values()) / max((fecha_emision - min(hist)).days, 1)
        predicciones[pid] = round(max(pred, 0), 1)

    return predicciones


# ─── Dashboard IA ──────────────────────────────────────────────────

def dashboard_ia(db: Session) -> dict:
    """Dashboard consolidado de IA: resumen rápido."""
    # Production suggestions for tomorrow
    hoy = operation_today()
    productos = _productos(db)
    historial = _ventas_diarias(db, hoy - timedelta(weeks=9, days=1), hoy - timedelta(days=1))
    sugerencias = pronostico_produccion_ia(db, historial=historial, productos=productos)
    top_hornear = [s for s in sugerencias if s["sugerido_hornear"] > 0][:5]

    # Pricing alerts
    pricing = analisis_pricing(db, dias=30, productos=productos)
    alertas_precio = [p for p in pricing if p["sugerencia"]["accion"] != "mantener"][:5]

    # Model accuracy
    precision = precision_modelo(db, dias_atras=7, historial=historial)

    # Products not selling
    sin_venta = [p for p in pricing if p["dias_sin_venta"] > 7 and p["stock_actual"] > 0]

    # Potential monthly impact from pricing changes
    impacto_total = sum(
        p["sugerencia"].get("impacto_mensual", 0)
        for p in pricing if p["sugerencia"]["accion"] in ("subir",)
    )

    return {
        "sugerencias_produccion": top_hornear,
        "total_productos_hornear": sum(s["sugerido_hornear"] > 0 for s in sugerencias),
        "alertas_pricing": alertas_precio,
        "precision_modelo": {
            "valor": precision["precision_promedio"],
            "calificacion": precision["calificacion"],
            "muestras": precision["muestras"],
        },
        "productos_sin_rotacion": len(sin_venta),
        "impacto_potencial_mensual": round(impacto_total, 2),
        "total_productos_analizados": len(pricing),
        "fecha_base": (hoy - timedelta(days=1)).isoformat(),
        "advertencias": [s["nombre"] + ": " + aviso for s in sugerencias for aviso in s["advertencias"]],
    }


# ─── Helpers ──────────────────────────────────────────────────────

def _nombre_dia(dow: int) -> str:
    return ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"][dow]
