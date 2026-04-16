"""
Servicio de control de calidad y trazabilidad.
Inspecciones, trazabilidad de lotes, alertas de recall e indicadores.
"""

import json
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.calidad import (
    ChecklistCalidad, EstadoInspeccion, TrazabilidadLote, AlertaRecall,
)
from app.models.inventario import LoteIngrediente, Producto
from app.models.receta import OrdenProduccion
from app.schemas.calidad import (
    ChecklistCalidadCreate, TrazabilidadLoteCreate, AlertaRecallCreate,
)


# --- Checklists de calidad ---

def _calcular_calificacion_global(
    apariencia: int | None,
    textura: int | None,
    sabor: int | None,
) -> Decimal | None:
    """Calcula el promedio de las puntuaciones sensoriales."""
    valores = [v for v in (apariencia, textura, sabor) if v is not None]
    if not valores:
        return None
    promedio = sum(valores) / len(valores)
    return Decimal(str(round(promedio, 1)))


def crear_checklist(db: Session, data: ChecklistCalidadCreate) -> ChecklistCalidad:
    """Crea un checklist de calidad y computa la calificacion global."""
    calificacion = _calcular_calificacion_global(
        data.apariencia, data.textura, data.sabor,
    )
    checklist = ChecklistCalidad(
        orden_produccion_id=data.orden_produccion_id,
        producto_id=data.producto_id,
        fecha_inspeccion=data.fecha_inspeccion,
        inspector_id=data.inspector_id,
        estado=EstadoInspeccion(data.estado),
        apariencia=data.apariencia,
        textura=data.textura,
        sabor=data.sabor,
        peso_correcto=data.peso_correcto,
        empaque_correcto=data.empaque_correcto,
        temperatura_correcta=data.temperatura_correcta,
        peso_muestra=data.peso_muestra,
        temperatura_muestra=data.temperatura_muestra,
        observaciones=data.observaciones,
        foto_url=data.foto_url,
        calificacion_global=calificacion,
    )
    db.add(checklist)
    db.commit()
    db.refresh(checklist)
    return checklist


def listar_checklists(
    db: Session,
    producto_id: int | None = None,
    estado: str | None = None,
    fecha_inicio: str | None = None,
    fecha_fin: str | None = None,
) -> list[ChecklistCalidad]:
    """Lista checklists con filtros opcionales."""
    query = db.query(ChecklistCalidad)
    if producto_id is not None:
        query = query.filter(ChecklistCalidad.producto_id == producto_id)
    if estado is not None:
        query = query.filter(ChecklistCalidad.estado == EstadoInspeccion(estado))
    if fecha_inicio is not None:
        query = query.filter(ChecklistCalidad.fecha_inspeccion >= fecha_inicio)
    if fecha_fin is not None:
        query = query.filter(ChecklistCalidad.fecha_inspeccion <= fecha_fin)
    return query.order_by(ChecklistCalidad.creado_en.desc()).all()


def obtener_checklist(db: Session, checklist_id: int) -> ChecklistCalidad:
    """Obtiene un checklist por su ID."""
    checklist = db.query(ChecklistCalidad).filter(
        ChecklistCalidad.id == checklist_id
    ).first()
    if not checklist:
        raise ValueError("Checklist de calidad no encontrado")
    return checklist


# --- Trazabilidad ---

def registrar_trazabilidad(
    db: Session, data: TrazabilidadLoteCreate,
) -> TrazabilidadLote:
    """Registra el uso de un lote de ingrediente en produccion."""
    # Verificar que el lote existe
    lote = db.query(LoteIngrediente).filter(
        LoteIngrediente.id == data.lote_ingrediente_id
    ).first()
    if not lote:
        raise ValueError("Lote de ingrediente no encontrado")

    registro = TrazabilidadLote(
        lote_ingrediente_id=data.lote_ingrediente_id,
        orden_produccion_id=data.orden_produccion_id,
        producto_id=data.producto_id,
        cantidad_usada=data.cantidad_usada,
        notas=data.notas,
    )
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def trazabilidad_producto(db: Session, producto_id: int) -> list[dict]:
    """Trazabilidad hacia adelante: que lotes se usaron para hacer este producto."""
    registros = db.query(TrazabilidadLote).filter(
        TrazabilidadLote.producto_id == producto_id
    ).order_by(TrazabilidadLote.fecha_uso.desc()).all()

    resultado = []
    for reg in registros:
        lote = db.query(LoteIngrediente).filter(
            LoteIngrediente.id == reg.lote_ingrediente_id
        ).first()
        resultado.append({
            "trazabilidad_id": reg.id,
            "lote_ingrediente_id": reg.lote_ingrediente_id,
            "numero_lote": lote.numero_lote if lote else None,
            "ingrediente_id": lote.ingrediente_id if lote else None,
            "orden_produccion_id": reg.orden_produccion_id,
            "cantidad_usada": float(reg.cantidad_usada),
            "fecha_uso": reg.fecha_uso.isoformat() if reg.fecha_uso else None,
            "fecha_caducidad": lote.fecha_caducidad.isoformat() if lote and lote.fecha_caducidad else None,
            "proveedor_id": lote.proveedor_id if lote else None,
            "notas": reg.notas,
        })
    return resultado


def trazabilidad_lote(db: Session, lote_id: int) -> list[dict]:
    """Trazabilidad inversa: que productos se hicieron con este lote."""
    registros = db.query(TrazabilidadLote).filter(
        TrazabilidadLote.lote_ingrediente_id == lote_id
    ).order_by(TrazabilidadLote.fecha_uso.desc()).all()

    resultado = []
    for reg in registros:
        producto = None
        if reg.producto_id:
            producto = db.query(Producto).filter(
                Producto.id == reg.producto_id
            ).first()
        resultado.append({
            "trazabilidad_id": reg.id,
            "producto_id": reg.producto_id,
            "producto_nombre": producto.nombre if producto else None,
            "orden_produccion_id": reg.orden_produccion_id,
            "cantidad_usada": float(reg.cantidad_usada),
            "fecha_uso": reg.fecha_uso.isoformat() if reg.fecha_uso else None,
            "notas": reg.notas,
        })
    return resultado


# --- Alertas de recall ---

def crear_alerta_recall(
    db: Session, data: AlertaRecallCreate, usuario_id: int,
) -> AlertaRecall:
    """Crea una alerta de recall y auto-detecta productos afectados via trazabilidad."""
    # Buscar productos afectados via trazabilidad del lote
    registros = db.query(TrazabilidadLote).filter(
        TrazabilidadLote.lote_ingrediente_id == data.lote_ingrediente_id
    ).all()

    productos_ids = list({
        reg.producto_id for reg in registros if reg.producto_id is not None
    })

    alerta = AlertaRecall(
        lote_ingrediente_id=data.lote_ingrediente_id,
        motivo=data.motivo,
        severidad=data.severidad,
        productos_afectados=json.dumps(productos_ids),
        estado="abierta",
        reportado_por=usuario_id,
    )
    db.add(alerta)
    db.commit()
    db.refresh(alerta)
    return alerta


def listar_alertas_recall(
    db: Session, estado: str | None = None,
    skip: int = 0, limit: int = 100) -> list[AlertaRecall]:
    """Lista alertas de recall con filtro opcional de estado."""
    query = db.query(AlertaRecall)
    if estado is not None:
        query = query.filter(AlertaRecall.estado == estado)
    return query.order_by(AlertaRecall.creado_en.desc()).offset(skip).limit(limit).all()


def resolver_recall(
    db: Session, recall_id: int, acciones: str,
) -> AlertaRecall:
    """Marca una alerta de recall como resuelta."""
    alerta = db.query(AlertaRecall).filter(AlertaRecall.id == recall_id).first()
    if not alerta:
        raise ValueError("Alerta de recall no encontrada")
    if alerta.estado == "resuelta":
        raise ValueError("Esta alerta ya fue resuelta")

    alerta.acciones_tomadas = acciones
    alerta.estado = "resuelta"
    alerta.resuelto_en = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alerta)
    return alerta


# --- Indicadores y dashboard ---

def indicadores_calidad(db: Session, dias: int = 30) -> dict:
    """KPIs de calidad para los ultimos N dias."""
    fecha_corte = datetime.now(timezone.utc) - timedelta(days=dias)

    total = db.query(func.count(ChecklistCalidad.id)).filter(
        ChecklistCalidad.creado_en >= fecha_corte
    ).scalar() or 0

    aprobados = db.query(func.count(ChecklistCalidad.id)).filter(
        ChecklistCalidad.creado_en >= fecha_corte,
        ChecklistCalidad.estado == EstadoInspeccion.APROBADO,
    ).scalar() or 0

    rechazados = db.query(func.count(ChecklistCalidad.id)).filter(
        ChecklistCalidad.creado_en >= fecha_corte,
        ChecklistCalidad.estado == EstadoInspeccion.RECHAZADO,
    ).scalar() or 0

    promedio_calificacion = db.query(
        func.avg(ChecklistCalidad.calificacion_global)
    ).filter(
        ChecklistCalidad.creado_en >= fecha_corte,
        ChecklistCalidad.calificacion_global.isnot(None),
    ).scalar()

    return {
        "dias": dias,
        "total_inspecciones": total,
        "aprobados": aprobados,
        "rechazados": rechazados,
        "porcentaje_aprobados": round((aprobados / total) * 100, 1) if total > 0 else 0.0,
        "porcentaje_rechazados": round((rechazados / total) * 100, 1) if total > 0 else 0.0,
        "calificacion_promedio": float(promedio_calificacion) if promedio_calificacion else None,
    }


def dashboard_calidad(db: Session) -> dict:
    """Dashboard resumen de calidad: indicadores, alertas activas, ultimos checklists."""
    kpis = indicadores_calidad(db, dias=30)

    alertas_activas = db.query(AlertaRecall).filter(
        AlertaRecall.estado.in_(["abierta", "en_proceso"])
    ).order_by(AlertaRecall.creado_en.desc()).all()

    ultimos_checklists = db.query(ChecklistCalidad).order_by(
        ChecklistCalidad.creado_en.desc()
    ).limit(10).all()

    # Productos sin inspeccion reciente (ultimos 7 dias)
    fecha_corte = datetime.now(timezone.utc) - timedelta(days=7)
    productos_inspeccionados = db.query(
        ChecklistCalidad.producto_id
    ).filter(
        ChecklistCalidad.creado_en >= fecha_corte
    ).distinct().subquery()

    productos_sin_inspeccion = db.query(Producto).filter(
        Producto.activo.is_(True),
        Producto.id.notin_(
            db.query(productos_inspeccionados.c.producto_id)
        ),
    ).all()

    return {
        "indicadores": kpis,
        "alertas_activas": [
            {
                "id": a.id,
                "lote_ingrediente_id": a.lote_ingrediente_id,
                "motivo": a.motivo,
                "severidad": a.severidad,
                "estado": a.estado,
                "productos_afectados": a.productos_afectados,
                "creado_en": a.creado_en.isoformat() if a.creado_en else None,
            }
            for a in alertas_activas
        ],
        "ultimos_checklists": [
            {
                "id": c.id,
                "producto_id": c.producto_id,
                "estado": c.estado.value if hasattr(c.estado, "value") else c.estado,
                "calificacion_global": float(c.calificacion_global) if c.calificacion_global else None,
                "fecha_inspeccion": c.fecha_inspeccion.isoformat() if c.fecha_inspeccion else None,
                "inspector_id": c.inspector_id,
            }
            for c in ultimos_checklists
        ],
        "productos_sin_inspeccion_reciente": [
            {"id": p.id, "nombre": p.nombre, "codigo": p.codigo}
            for p in productos_sin_inspeccion
        ],
    }
