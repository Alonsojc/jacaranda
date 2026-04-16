"""
Servicio de optimización de producción.
Predicción de demanda basada en historial de ventas y planificación inteligente.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from collections import defaultdict

from sqlalchemy import func, and_
from sqlalchemy.orm import Session, joinedload

from app.models.venta import Venta, DetalleVenta, EstadoVenta
from app.models.inventario import Producto, Ingrediente
from app.models.receta import Receta, RecetaIngrediente, OrdenProduccion, EstadoProduccion


# ─── Predicción de demanda ────────────────────────────────────────

def predecir_demanda(db: Session, dias_prediccion: int = 7, semanas_historial: int = 8) -> list[dict]:
    """
    Predice la demanda de cada producto para los próximos N días
    basándose en el historial de ventas ponderado por recencia y día de la semana.
    """
    hoy = date.today()
    inicio_historial = hoy - timedelta(weeks=semanas_historial)

    # Obtener ventas históricas por producto y día de la semana
    ventas = (
        db.query(
            DetalleVenta.producto_id,
            Venta.fecha,
            func.sum(DetalleVenta.cantidad).label("cantidad"),
        )
        .join(Venta)
        .filter(
            and_(
                Venta.fecha >= datetime.combine(inicio_historial, datetime.min.time()),
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        )
        .group_by(DetalleVenta.producto_id, Venta.fecha)
        .all()
    )

    # Agrupar por producto y día de la semana con pesos por recencia
    ventas_por_producto: dict[int, dict[int, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for v in ventas:
        if v.fecha is None:
            continue
        producto_id = v.producto_id
        if isinstance(v.fecha, datetime):
            fecha = v.fecha.date()
        elif isinstance(v.fecha, date):
            fecha = v.fecha
        else:
            continue
        dow = fecha.weekday()  # 0=Mon, 6=Sun
        dias_atras = (hoy - fecha).days
        # Peso exponencial: más reciente = más peso
        peso = max(0.1, 1.0 - (dias_atras / (semanas_historial * 7)))
        cantidad = float(v.cantidad)
        ventas_por_producto[producto_id][dow].append((cantidad, peso))

    # Calcular predicción por producto
    predicciones = []
    productos = db.query(Producto).filter(Producto.activo.is_(True)).all()

    for producto in productos:
        pid = producto.id
        demanda_diaria = []

        for dia_offset in range(dias_prediccion):
            dia_futuro = hoy + timedelta(days=dia_offset)
            dow = dia_futuro.weekday()
            datos_dia = ventas_por_producto.get(pid, {}).get(dow, [])

            if datos_dia:
                # Media ponderada
                total_peso = sum(p for _, p in datos_dia)
                if total_peso > 0:
                    promedio = sum(c * p for c, p in datos_dia) / total_peso
                else:
                    promedio = sum(c for c, _ in datos_dia) / len(datos_dia)
            else:
                # Sin datos para este día, usar promedio general del producto
                todas = ventas_por_producto.get(pid, {})
                todas_vals = [c for dow_list in todas.values() for c, _ in dow_list]
                promedio = sum(todas_vals) / len(todas_vals) if todas_vals else 0

            demanda_diaria.append({
                "fecha": dia_futuro.isoformat(),
                "dia_semana": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][dow],
                "cantidad_estimada": round(promedio, 1),
            })

        total_semana = sum(d["cantidad_estimada"] for d in demanda_diaria)

        if total_semana > 0:
            predicciones.append({
                "producto_id": pid,
                "producto_nombre": producto.nombre,
                "stock_actual": float(producto.stock_actual),
                "demanda_semanal_estimada": round(total_semana, 1),
                "requiere_produccion": total_semana > float(producto.stock_actual),
                "deficit": round(max(0, total_semana - float(producto.stock_actual)), 1),
                "demanda_diaria": demanda_diaria,
            })

    # Ordenar por déficit descendente (prioridad de producción)
    predicciones.sort(key=lambda x: x["deficit"], reverse=True)
    return predicciones


# ─── Plan de producción ───────────────────────────────────────────

def generar_plan_produccion(db: Session, dias: int = 7) -> dict:
    """
    Genera un plan de producción basado en la predicción de demanda.
    Calcula qué recetas preparar, ingredientes necesarios y horarios sugeridos.
    """
    predicciones = predecir_demanda(db, dias_prediccion=dias)
    productos_con_deficit = [p for p in predicciones if p["requiere_produccion"]]

    plan_items = []
    ingredientes_totales: dict[int, dict] = {}

    for pred in productos_con_deficit:
        producto = db.query(Producto).filter(Producto.id == pred["producto_id"]).first()
        if not producto:
            continue

        # Buscar receta del producto
        receta = db.query(Receta).filter(Receta.producto_id == producto.id).first()
        if not receta:
            plan_items.append({
                "producto_id": producto.id,
                "producto_nombre": producto.nombre,
                "cantidad_producir": pred["deficit"],
                "receta": None,
                "lotes_necesarios": 0,
                "ingredientes": [],
                "nota": "Sin receta asociada",
            })
            continue

        # Calcular lotes necesarios
        rendimiento = float(receta.rendimiento) if receta.rendimiento else 1
        lotes = max(1, int(pred["deficit"] / rendimiento) + (1 if pred["deficit"] % rendimiento > 0 else 0))

        # Calcular ingredientes necesarios
        ingredientes_receta = []
        for ri in receta.ingredientes:
            ingrediente = db.query(Ingrediente).filter(
                Ingrediente.id == ri.ingrediente_id
            ).first()
            if not ingrediente:
                continue

            cantidad_necesaria = float(ri.cantidad) * lotes
            stock_actual = float(ingrediente.stock_actual)
            suficiente = stock_actual >= cantidad_necesaria

            ingredientes_receta.append({
                "ingrediente_id": ingrediente.id,
                "nombre": ingrediente.nombre,
                "cantidad_necesaria": round(cantidad_necesaria, 2),
                "stock_actual": stock_actual,
                "unidad": ingrediente.unidad_medida.value if ingrediente.unidad_medida else "pz",
                "suficiente": suficiente,
                "deficit": round(max(0, cantidad_necesaria - stock_actual), 2),
            })

            # Acumular ingredientes totales
            if ingrediente.id not in ingredientes_totales:
                ingredientes_totales[ingrediente.id] = {
                    "ingrediente_id": ingrediente.id,
                    "nombre": ingrediente.nombre,
                    "unidad": ingrediente.unidad_medida.value if ingrediente.unidad_medida else "pz",
                    "cantidad_necesaria": 0,
                    "stock_actual": stock_actual,
                }
            ingredientes_totales[ingrediente.id]["cantidad_necesaria"] += cantidad_necesaria

        plan_items.append({
            "producto_id": producto.id,
            "producto_nombre": producto.nombre,
            "cantidad_producir": pred["deficit"],
            "receta": receta.nombre,
            "receta_id": receta.id,
            "lotes_necesarios": lotes,
            "tiempo_estimado_min": (
                (receta.tiempo_preparacion_min or 0) + (receta.tiempo_horneado_min or 0)
            ) * lotes,
            "ingredientes": ingredientes_receta,
        })

    # Calcular resumen de ingredientes
    resumen_ingredientes = []
    for ing_data in ingredientes_totales.values():
        ing_data["deficit"] = round(
            max(0, ing_data["cantidad_necesaria"] - ing_data["stock_actual"]), 2
        )
        ing_data["cantidad_necesaria"] = round(ing_data["cantidad_necesaria"], 2)
        ing_data["requiere_compra"] = ing_data["deficit"] > 0
        resumen_ingredientes.append(ing_data)

    # Ordenar ingredientes que requieren compra primero
    resumen_ingredientes.sort(key=lambda x: x["deficit"], reverse=True)

    # Tiempo total estimado
    tiempo_total = sum(item.get("tiempo_estimado_min", 0) for item in plan_items)

    return {
        "periodo": f"{date.today().isoformat()} a {(date.today() + timedelta(days=dias)).isoformat()}",
        "productos_a_producir": len(plan_items),
        "tiempo_total_estimado_min": tiempo_total,
        "tiempo_total_estimado_hrs": round(tiempo_total / 60, 1),
        "plan": plan_items,
        "ingredientes_consolidados": resumen_ingredientes,
        "ingredientes_por_comprar": [i for i in resumen_ingredientes if i["requiere_compra"]],
    }


# ─── Análisis de eficiencia ───────────────────────────────────────

def analisis_eficiencia(db: Session, dias: int = 30) -> dict:
    """
    Analiza la eficiencia de producción: merma vs producción,
    productos sobre/sub producidos, tendencias.
    """
    hoy = date.today()
    inicio = hoy - timedelta(days=dias)

    # Producción en el periodo
    ordenes = (
        db.query(OrdenProduccion)
        .options(joinedload(OrdenProduccion.receta))
        .filter(
            and_(
                OrdenProduccion.fecha_inicio >= datetime.combine(inicio, datetime.min.time()),
                OrdenProduccion.estado == EstadoProduccion.COMPLETADA,
            )
        )
        .all()
    )

    produccion_por_producto: dict[int, float] = defaultdict(float)
    for orden in ordenes:
        # producto_id se obtiene a través de la receta
        if orden.receta and orden.receta.producto_id:
            produccion_por_producto[orden.receta.producto_id] += float(orden.cantidad_producida or 0)

    # Ventas en el periodo
    ventas = (
        db.query(
            DetalleVenta.producto_id,
            func.sum(DetalleVenta.cantidad).label("cantidad"),
        )
        .join(Venta)
        .filter(
            and_(
                Venta.fecha >= datetime.combine(inicio, datetime.min.time()),
                Venta.estado == EstadoVenta.COMPLETADA,
            )
        )
        .group_by(DetalleVenta.producto_id)
        .all()
    )

    ventas_por_producto = {v.producto_id: float(v.cantidad) for v in ventas}

    # Comparar producción vs ventas
    analisis_productos = []
    for pid, producido in produccion_por_producto.items():
        vendido = ventas_por_producto.get(pid, 0)
        producto = db.query(Producto).filter(Producto.id == pid).first()

        ratio = vendido / producido if producido > 0 else 0
        desperdicio_pct = max(0, (producido - vendido) / producido * 100) if producido > 0 else 0

        analisis_productos.append({
            "producto_id": pid,
            "producto_nombre": producto.nombre if producto else f"#{pid}",
            "producido": round(producido, 1),
            "vendido": round(vendido, 1),
            "ratio_venta_produccion": round(ratio, 2),
            "desperdicio_estimado_pct": round(desperdicio_pct, 1),
            "clasificacion": (
                "optimo" if 0.85 <= ratio <= 1.0
                else "sobreproduccion" if ratio < 0.85
                else "subproduccion"
            ),
        })

    analisis_productos.sort(key=lambda x: x["ratio_venta_produccion"])

    # KPIs
    total_producido = sum(a["producido"] for a in analisis_productos)
    total_vendido = sum(a["vendido"] for a in analisis_productos)
    eficiencia_global = total_vendido / total_producido * 100 if total_producido > 0 else 0

    return {
        "periodo_dias": dias,
        "eficiencia_global_pct": round(eficiencia_global, 1),
        "total_producido": round(total_producido, 1),
        "total_vendido": round(total_vendido, 1),
        "ordenes_completadas": len(ordenes),
        "productos_sobreproduccion": len([a for a in analisis_productos if a["clasificacion"] == "sobreproduccion"]),
        "productos_subproduccion": len([a for a in analisis_productos if a["clasificacion"] == "subproduccion"]),
        "productos_optimos": len([a for a in analisis_productos if a["clasificacion"] == "optimo"]),
        "detalle_productos": analisis_productos,
    }


# ─── Dashboard de producción ──────────────────────────────────────

def dashboard_produccion(db: Session) -> dict:
    """Dashboard consolidado de producción y planificación."""
    # Predicción resumida (próximos 7 días)
    prediccion = predecir_demanda(db, dias_prediccion=7)
    productos_con_deficit = [p for p in prediccion if p["requiere_produccion"]]

    # Órdenes activas
    ordenes_activas = (
        db.query(func.count(OrdenProduccion.id))
        .filter(OrdenProduccion.estado.in_([EstadoProduccion.PLANIFICADA, EstadoProduccion.EN_PROCESO]))
        .scalar()
    ) or 0

    ordenes_hoy = (
        db.query(func.count(OrdenProduccion.id))
        .filter(
            and_(
                OrdenProduccion.fecha_inicio >= datetime.combine(date.today(), datetime.min.time()),
                OrdenProduccion.estado == EstadoProduccion.COMPLETADA,
            )
        )
        .scalar()
    ) or 0

    # Eficiencia (últimos 30 días)
    eficiencia = analisis_eficiencia(db, dias=30)

    return {
        "fecha": date.today().isoformat(),
        "ordenes_activas": ordenes_activas,
        "ordenes_completadas_hoy": ordenes_hoy,
        "productos_con_deficit": len(productos_con_deficit),
        "top_deficit": [
            {
                "producto": p["producto_nombre"],
                "deficit": p["deficit"],
                "demanda_semanal": p["demanda_semanal_estimada"],
            }
            for p in productos_con_deficit[:5]
        ],
        "eficiencia_global_pct": eficiencia["eficiencia_global_pct"],
        "total_productos_prediccion": len(prediccion),
    }
