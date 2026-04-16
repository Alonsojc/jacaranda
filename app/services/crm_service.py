"""
Servicio del módulo CRM y Marketing.
Segmentación RFM, campañas, encuestas de satisfacción, predicción de churn.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.cliente import Cliente
from app.models.venta import Venta, EstadoVenta
from app.models.crm import (
    Campana, EncuestaSatisfaccion, InteraccionCliente, SegmentoCliente,
)


# ── Segmentación RFM ───────────────────────────────────────────────


def _calcular_segmento(recencia_dias: int, frecuencia: int, monto_total: float) -> SegmentoCliente:
    """Determina el segmento de un cliente según métricas RFM."""
    if recencia_dias > 120:
        return SegmentoCliente.PERDIDO
    if recencia_dias > 60:
        return SegmentoCliente.DORMIDO
    if recencia_dias > 30:
        return SegmentoCliente.EN_RIESGO

    # Cliente activo (compró en los últimos 30 días)
    if frecuencia >= 8 and monto_total >= 2000:
        return SegmentoCliente.VIP
    if frecuencia >= 3 or monto_total >= 800:
        return SegmentoCliente.LEAL
    return SegmentoCliente.NUEVO


def segmentar_clientes(db: Session) -> list[dict]:
    """
    Ejecuta análisis RFM sobre todos los clientes activos.
    R = días desde la última compra
    F = número de compras en los últimos 90 días
    M = monto total gastado en los últimos 90 días
    """
    ahora = datetime.now(timezone.utc)
    hace_90_dias = ahora - timedelta(days=90)

    clientes = db.query(Cliente).filter(Cliente.activo.is_(True)).all()
    resultados = []

    for cliente in clientes:
        # Recencia: última compra
        ultima_venta = (
            db.query(func.max(Venta.fecha))
            .filter(
                Venta.cliente_id == cliente.id,
                Venta.estado == EstadoVenta.COMPLETADA,
            )
            .scalar()
        )

        if ultima_venta is None:
            recencia_dias = 999
        else:
            if ultima_venta.tzinfo is None:
                recencia_dias = (ahora.replace(tzinfo=None) - ultima_venta).days
            else:
                recencia_dias = (ahora - ultima_venta).days

        # Frecuencia y monto en últimos 90 días
        stats = (
            db.query(
                func.count(Venta.id),
                func.coalesce(func.sum(Venta.total), 0),
            )
            .filter(
                Venta.cliente_id == cliente.id,
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= hace_90_dias,
            )
            .first()
        )
        frecuencia = stats[0] or 0
        monto_total = float(stats[1] or 0)

        segmento = _calcular_segmento(recencia_dias, frecuencia, monto_total)

        resultados.append({
            "cliente_id": cliente.id,
            "nombre": cliente.nombre,
            "segmento": segmento.value,
            "recencia_dias": recencia_dias,
            "frecuencia": frecuencia,
            "monto_total": monto_total,
        })

    return resultados


def obtener_segmentacion(db: Session) -> dict:
    """Resumen de segmentación: conteo por segmento y total de clientes."""
    clientes_segmentados = segmentar_clientes(db)

    conteo = {s.value: 0 for s in SegmentoCliente}
    for c in clientes_segmentados:
        conteo[c["segmento"]] += 1

    return {
        "segmentos": conteo,
        "total_clientes": len(clientes_segmentados),
    }


def clientes_en_riesgo(db: Session) -> list[dict]:
    """
    Clientes cuya última compra fue hace 30-60 días (en_riesgo)
    o 60+ días (dormido/perdido).
    """
    todos = segmentar_clientes(db)
    segmentos_riesgo = {
        SegmentoCliente.EN_RIESGO.value,
        SegmentoCliente.DORMIDO.value,
        SegmentoCliente.PERDIDO.value,
    }
    return [c for c in todos if c["segmento"] in segmentos_riesgo]


# ── Campañas ────────────────────────────────────────────────────────


def crear_campana(db: Session, data: dict) -> dict:
    """Crea una nueva campaña de marketing."""
    campana = Campana(**data)
    db.add(campana)
    db.flush()
    db.refresh(campana)
    return {
        "id": campana.id,
        "nombre": campana.nombre,
        "tipo": campana.tipo,
        "segmento_objetivo": campana.segmento_objetivo,
        "estado": campana.estado,
        "fecha_inicio": str(campana.fecha_inicio),
        "fecha_fin": str(campana.fecha_fin) if campana.fecha_fin else None,
    }


def listar_campanas(db: Session, skip: int = 0, limit: int = 100) -> list[dict]:
    """Lista todas las campañas ordenadas por fecha de creación."""
    campanas = db.query(Campana).order_by(Campana.creado_en.desc()).offset(skip).limit(limit).all()
    return [
        {
            "id": c.id,
            "nombre": c.nombre,
            "tipo": c.tipo,
            "segmento_objetivo": c.segmento_objetivo,
            "estado": c.estado,
            "fecha_inicio": str(c.fecha_inicio),
            "fecha_fin": str(c.fecha_fin) if c.fecha_fin else None,
            "enviados": c.enviados,
            "abiertos": c.abiertos,
            "conversiones": c.conversiones,
        }
        for c in campanas
    ]


def ejecutar_campana(db: Session, campana_id: int) -> dict:
    """
    Simula la ejecución de una campaña: cuenta clientes del segmento objetivo,
    actualiza conteo de enviados y pone estado en activa.
    """
    campana = db.query(Campana).filter(Campana.id == campana_id).first()
    if not campana:
        raise ValueError("Campaña no encontrada")

    if campana.estado not in ("borrador", "pausada"):
        raise ValueError(f"No se puede ejecutar una campaña con estado '{campana.estado}'")

    # Contar clientes del segmento objetivo
    if campana.segmento_objetivo:
        clientes_segmentados = segmentar_clientes(db)
        clientes_objetivo = [
            c for c in clientes_segmentados
            if c["segmento"] == campana.segmento_objetivo
        ]
        total_enviados = len(clientes_objetivo)
    else:
        # Sin segmento: enviar a todos los clientes activos
        total_enviados = (
            db.query(func.count(Cliente.id))
            .filter(Cliente.activo.is_(True))
            .scalar()
        ) or 0

    campana.enviados = total_enviados
    campana.estado = "activa"
    db.flush()

    return {
        "id": campana.id,
        "nombre": campana.nombre,
        "estado": campana.estado,
        "enviados": campana.enviados,
        "segmento_objetivo": campana.segmento_objetivo,
    }


# ── Encuestas de Satisfacción ──────────────────────────────────────


def registrar_encuesta(db: Session, data: dict) -> dict:
    """Registra una encuesta de satisfacción."""
    encuesta = EncuestaSatisfaccion(**data)
    db.add(encuesta)
    db.flush()
    db.refresh(encuesta)
    return {
        "id": encuesta.id,
        "cliente_id": encuesta.cliente_id,
        "calificacion": encuesta.calificacion,
        "categoria": encuesta.categoria,
        "comentario": encuesta.comentario,
    }


def resumen_satisfaccion(db: Session, dias: int = 30) -> dict:
    """
    Resumen de satisfacción: promedio, distribución por estrellas,
    por categoría y comentarios recientes.
    """
    desde = datetime.now(timezone.utc) - timedelta(days=dias)

    encuestas = (
        db.query(EncuestaSatisfaccion)
        .filter(EncuestaSatisfaccion.creado_en >= desde)
        .all()
    )

    if not encuestas:
        return {
            "promedio": 0,
            "total_encuestas": 0,
            "distribucion_estrellas": {str(i): 0 for i in range(1, 6)},
            "por_categoria": {},
            "comentarios_recientes": [],
        }

    # Promedio general
    calificaciones = [e.calificacion for e in encuestas]
    promedio = round(sum(calificaciones) / len(calificaciones), 2)

    # Distribución por estrellas
    distribucion = {str(i): 0 for i in range(1, 6)}
    for cal in calificaciones:
        distribucion[str(cal)] += 1

    # Por categoría
    por_categoria: dict[str, list[int]] = {}
    for e in encuestas:
        por_categoria.setdefault(e.categoria, []).append(e.calificacion)
    por_categoria_resumen = {
        cat: round(sum(vals) / len(vals), 2)
        for cat, vals in por_categoria.items()
    }

    # Comentarios recientes (últimos 10 con comentario)
    comentarios_recientes = [
        {
            "cliente_id": e.cliente_id,
            "calificacion": e.calificacion,
            "categoria": e.categoria,
            "comentario": e.comentario,
            "fecha": e.creado_en.isoformat() if e.creado_en else None,
        }
        for e in sorted(encuestas, key=lambda x: x.creado_en or datetime.min, reverse=True)
        if e.comentario
    ][:10]

    return {
        "promedio": promedio,
        "total_encuestas": len(encuestas),
        "distribucion_estrellas": distribucion,
        "por_categoria": por_categoria_resumen,
        "comentarios_recientes": comentarios_recientes,
    }


# ── Interacciones ──────────────────────────────────────────────────


def registrar_interaccion(db: Session, data: dict) -> dict:
    """Registra una interacción con un cliente."""
    interaccion = InteraccionCliente(**data)
    db.add(interaccion)
    db.flush()
    db.refresh(interaccion)
    return {
        "id": interaccion.id,
        "cliente_id": interaccion.cliente_id,
        "tipo": interaccion.tipo,
        "canal": interaccion.canal,
        "descripcion": interaccion.descripcion,
        "resultado": interaccion.resultado,
    }


def listar_interacciones(db: Session, cliente_id: int, skip: int = 0, limit: int = 100) -> list[dict]:
    """Lista las interacciones de un cliente, ordenadas por fecha descendente."""
    interacciones = (
        db.query(InteraccionCliente)
        .filter(InteraccionCliente.cliente_id == cliente_id)
        .order_by(InteraccionCliente.creado_en.desc())
        .offset(skip).limit(limit).all()
    )
    return [
        {
            "id": i.id,
            "cliente_id": i.cliente_id,
            "tipo": i.tipo,
            "canal": i.canal,
            "descripcion": i.descripcion,
            "resultado": i.resultado,
            "usuario_id": i.usuario_id,
            "fecha": i.creado_en.isoformat() if i.creado_en else None,
        }
        for i in interacciones
    ]


# ── Predicción de Churn ────────────────────────────────────────────


def prediccion_churn(db: Session) -> list[dict]:
    """
    Lista clientes con alta probabilidad de abandono:
    última compra hace >45 días y tendencia de frecuencia decreciente.
    Compara frecuencia de los últimos 90 días vs los 90 días anteriores.
    """
    ahora = datetime.now(timezone.utc)
    hace_45_dias = ahora - timedelta(days=45)
    hace_90_dias = ahora - timedelta(days=90)
    hace_180_dias = ahora - timedelta(days=180)

    clientes = db.query(Cliente).filter(Cliente.activo.is_(True)).all()
    en_riesgo_churn = []

    for cliente in clientes:
        # Última compra
        ultima_venta = (
            db.query(func.max(Venta.fecha))
            .filter(
                Venta.cliente_id == cliente.id,
                Venta.estado == EstadoVenta.COMPLETADA,
            )
            .scalar()
        )

        if ultima_venta is None:
            continue

        if ultima_venta.tzinfo is None:
            dias_sin_compra = (ahora.replace(tzinfo=None) - ultima_venta).days
        else:
            dias_sin_compra = (ahora - ultima_venta).days

        if dias_sin_compra <= 45:
            continue

        # Frecuencia período reciente (últimos 90 días)
        freq_reciente = (
            db.query(func.count(Venta.id))
            .filter(
                Venta.cliente_id == cliente.id,
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= hace_90_dias,
            )
            .scalar()
        ) or 0

        # Frecuencia período anterior (90-180 días atrás)
        freq_anterior = (
            db.query(func.count(Venta.id))
            .filter(
                Venta.cliente_id == cliente.id,
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.fecha >= hace_180_dias,
                Venta.fecha < hace_90_dias,
            )
            .scalar()
        ) or 0

        # Tendencia decreciente: frecuencia reciente menor que la anterior
        tendencia_decreciente = freq_reciente < freq_anterior

        # Incluir si última compra >45 días y tendencia decreciente (o sin compras recientes)
        if tendencia_decreciente or freq_reciente == 0:
            en_riesgo_churn.append({
                "cliente_id": cliente.id,
                "nombre": cliente.nombre,
                "dias_sin_compra": dias_sin_compra,
                "frecuencia_reciente": freq_reciente,
                "frecuencia_anterior": freq_anterior,
                "tendencia": "decreciente" if tendencia_decreciente else "sin_actividad",
            })

    return sorted(en_riesgo_churn, key=lambda x: x["dias_sin_compra"], reverse=True)


# ── Dashboard CRM ──────────────────────────────────────────────────


def dashboard_crm(db: Session) -> dict:
    """
    Resumen del dashboard CRM: segmentación, satisfacción promedio,
    campañas activas, clientes en riesgo y tasa de retención a 30 días.
    """
    # Segmentación
    segmentacion = obtener_segmentacion(db)

    # Satisfacción promedio (últimos 30 días)
    satisfaccion = resumen_satisfaccion(db, dias=30)

    # Campañas activas
    campanas_activas = (
        db.query(func.count(Campana.id))
        .filter(Campana.estado == "activa")
        .scalar()
    ) or 0

    # Clientes en riesgo
    riesgo = clientes_en_riesgo(db)
    clientes_en_riesgo_count = len(riesgo)

    # Tasa de retención a 30 días
    ahora = datetime.now(timezone.utc)
    hace_30_dias = ahora - timedelta(days=30)
    hace_60_dias = ahora - timedelta(days=60)

    # Clientes que compraron entre 30-60 días atrás
    clientes_periodo_anterior = (
        db.query(Venta.cliente_id)
        .filter(
            Venta.estado == EstadoVenta.COMPLETADA,
            Venta.cliente_id.isnot(None),
            Venta.fecha >= hace_60_dias,
            Venta.fecha < hace_30_dias,
        )
        .distinct()
        .all()
    )
    ids_anterior = {row[0] for row in clientes_periodo_anterior}

    # De esos, cuántos volvieron a comprar en los últimos 30 días
    if ids_anterior:
        retenidos = (
            db.query(Venta.cliente_id)
            .filter(
                Venta.estado == EstadoVenta.COMPLETADA,
                Venta.cliente_id.in_(ids_anterior),
                Venta.fecha >= hace_30_dias,
            )
            .distinct()
            .count()
        )
        tasa_retencion = round((retenidos / len(ids_anterior)) * 100, 1)
    else:
        tasa_retencion = 0.0

    return {
        "segmentacion": segmentacion,
        "satisfaccion_promedio": satisfaccion["promedio"],
        "campanas_activas": campanas_activas,
        "clientes_en_riesgo_count": clientes_en_riesgo_count,
        "tasa_retencion_30d": tasa_retencion,
    }
