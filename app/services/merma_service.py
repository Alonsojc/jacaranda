"""
Servicio de gestión de merma (desperdicio/pérdida).
Registro, consulta, reportes y alertas de caducidad.
"""

from decimal import Decimal
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models.merma import RegistroMerma, TipoMerma
from app.models.inventario import (
    Producto, Ingrediente, MovimientoInventario, LoteIngrediente,
    TipoMovimiento,
)


def registrar_merma(db: Session, data: dict) -> dict:
    """Registra merma, reduce stock y crea movimiento de inventario."""

    producto_id = data.get("producto_id")
    ingrediente_id = data.get("ingrediente_id")

    if not producto_id and not ingrediente_id:
        raise ValueError("Debe indicar producto_id o ingrediente_id")
    if producto_id and ingrediente_id:
        raise ValueError("Indique solo producto_id o ingrediente_id, no ambos")

    cantidad = Decimal(str(data["cantidad"]))
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a cero")

    tipo = TipoMerma(data["tipo"])
    costo_unitario = Decimal(str(data.get("costo_unitario", 0)))
    costo_total = Decimal(str(data.get("costo_total", 0)))
    fecha_merma = data.get("fecha_merma") or date.today()
    if isinstance(fecha_merma, str):
        fecha_merma = date.fromisoformat(fecha_merma)

    nombre_item = ""
    unidad_medida = data.get("unidad_medida", "pz")

    # Reducir stock del producto o ingrediente
    if producto_id:
        producto = db.query(Producto).filter(Producto.id == producto_id).first()
        if not producto:
            raise ValueError("Producto no encontrado")
        if producto.stock_actual < cantidad:
            raise ValueError(
                f"Stock insuficiente de '{producto.nombre}': "
                f"disponible {producto.stock_actual}, solicitado {cantidad}"
            )
        producto.stock_actual -= cantidad
        nombre_item = producto.nombre
        unidad_medida = data.get("unidad_medida") or producto.unidad_medida.value
        if not costo_unitario:
            costo_unitario = producto.costo_produccion or Decimal("0")

    if ingrediente_id:
        ingrediente = db.query(Ingrediente).filter(
            Ingrediente.id == ingrediente_id
        ).first()
        if not ingrediente:
            raise ValueError("Ingrediente no encontrado")
        if ingrediente.stock_actual < cantidad:
            raise ValueError(
                f"Stock insuficiente de '{ingrediente.nombre}': "
                f"disponible {ingrediente.stock_actual}, solicitado {cantidad}"
            )
        ingrediente.stock_actual -= cantidad
        nombre_item = ingrediente.nombre
        unidad_medida = data.get("unidad_medida") or ingrediente.unidad_medida.value
        if not costo_unitario:
            costo_unitario = ingrediente.costo_unitario or Decimal("0")

    if not costo_total:
        costo_total = cantidad * costo_unitario

    # Crear registro de merma
    registro = RegistroMerma(
        producto_id=producto_id,
        ingrediente_id=ingrediente_id,
        tipo=tipo,
        cantidad=cantidad,
        unidad_medida=unidad_medida,
        costo_unitario=costo_unitario,
        costo_total=costo_total,
        motivo=data.get("motivo"),
        lote_id=data.get("lote_id"),
        fecha_merma=fecha_merma,
        responsable_id=data.get("responsable_id"),
    )
    db.add(registro)

    # Crear movimiento de inventario
    tipo_mov = (
        TipoMovimiento.SALIDA_CADUCIDAD
        if tipo == TipoMerma.CADUCIDAD
        else TipoMovimiento.SALIDA_MERMA
    )
    movimiento = MovimientoInventario(
        tipo=tipo_mov,
        producto_id=producto_id,
        ingrediente_id=ingrediente_id,
        cantidad=cantidad,
        costo_unitario=costo_unitario,
        lote_id=data.get("lote_id"),
        referencia=f"Merma ({tipo.value}): {nombre_item}",
        notas=data.get("motivo"),
        usuario_id=data.get("responsable_id"),
    )
    db.add(movimiento)

    # Reducir cantidad disponible del lote si aplica
    lote_id = data.get("lote_id")
    if lote_id:
        lote = db.query(LoteIngrediente).filter(
            LoteIngrediente.id == lote_id
        ).first()
        if lote and lote.cantidad_disponible >= cantidad:
            lote.cantidad_disponible -= cantidad

    db.commit()
    db.refresh(registro)

    return {
        "id": registro.id,
        "producto_id": registro.producto_id,
        "ingrediente_id": registro.ingrediente_id,
        "tipo": registro.tipo.value,
        "cantidad": float(registro.cantidad),
        "unidad_medida": registro.unidad_medida,
        "costo_unitario": float(registro.costo_unitario),
        "costo_total": float(registro.costo_total),
        "motivo": registro.motivo,
        "lote_id": registro.lote_id,
        "fecha_merma": registro.fecha_merma.isoformat(),
        "responsable_id": registro.responsable_id,
        "creado_en": registro.creado_en.isoformat() if registro.creado_en else None,
        "nombre_item": nombre_item,
    }


def listar_mermas(
    db: Session,
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    tipo: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[dict]:
    """Lista registros de merma con filtros opcionales."""
    query = db.query(RegistroMerma)

    if fecha_inicio:
        query = query.filter(RegistroMerma.fecha_merma >= fecha_inicio)
    if fecha_fin:
        query = query.filter(RegistroMerma.fecha_merma <= fecha_fin)
    if tipo:
        query = query.filter(RegistroMerma.tipo == TipoMerma(tipo))

    registros = query.order_by(RegistroMerma.fecha_merma.desc()).offset(skip).limit(limit).all()

    resultados = []
    for r in registros:
        nombre = ""
        if r.producto_id:
            prod = db.query(Producto).filter(Producto.id == r.producto_id).first()
            nombre = prod.nombre if prod else ""
        elif r.ingrediente_id:
            ing = db.query(Ingrediente).filter(Ingrediente.id == r.ingrediente_id).first()
            nombre = ing.nombre if ing else ""

        resultados.append({
            "id": r.id,
            "producto_id": r.producto_id,
            "ingrediente_id": r.ingrediente_id,
            "nombre_item": nombre,
            "tipo": r.tipo.value,
            "cantidad": float(r.cantidad),
            "unidad_medida": r.unidad_medida,
            "costo_unitario": float(r.costo_unitario),
            "costo_total": float(r.costo_total),
            "motivo": r.motivo,
            "lote_id": r.lote_id,
            "fecha_merma": r.fecha_merma.isoformat(),
            "responsable_id": r.responsable_id,
            "creado_en": r.creado_en.isoformat() if r.creado_en else None,
        })

    return resultados


def resumen_merma(
    db: Session,
    fecha_inicio: date,
    fecha_fin: date,
) -> dict:
    """Resumen de merma: totales, por tipo y top 10 productos."""
    registros = db.query(RegistroMerma).filter(
        and_(
            RegistroMerma.fecha_merma >= fecha_inicio,
            RegistroMerma.fecha_merma <= fecha_fin,
        )
    ).all()

    total_kg = Decimal("0")
    total_pesos = Decimal("0")
    por_tipo: dict[str, dict] = {}

    for r in registros:
        total_kg += r.cantidad
        total_pesos += r.costo_total
        t = r.tipo.value
        if t not in por_tipo:
            por_tipo[t] = {"cantidad": Decimal("0"), "costo_total": Decimal("0"), "registros": 0}
        por_tipo[t]["cantidad"] += r.cantidad
        por_tipo[t]["costo_total"] += r.costo_total
        por_tipo[t]["registros"] += 1

    # Top 10 productos con mayor merma en pesos
    producto_merma: dict[int, dict] = {}
    for r in registros:
        if r.producto_id:
            if r.producto_id not in producto_merma:
                prod = db.query(Producto).filter(Producto.id == r.producto_id).first()
                producto_merma[r.producto_id] = {
                    "producto_id": r.producto_id,
                    "nombre": prod.nombre if prod else "Desconocido",
                    "cantidad": Decimal("0"),
                    "costo_total": Decimal("0"),
                }
            producto_merma[r.producto_id]["cantidad"] += r.cantidad
            producto_merma[r.producto_id]["costo_total"] += r.costo_total

    top_productos = sorted(
        producto_merma.values(), key=lambda x: x["costo_total"], reverse=True
    )[:10]

    return {
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": fecha_fin.isoformat(),
        "total_registros": len(registros),
        "total_kg": float(total_kg),
        "total_pesos": float(total_pesos),
        "por_tipo": {
            k: {
                "cantidad": float(v["cantidad"]),
                "costo_total": float(v["costo_total"]),
                "registros": v["registros"],
            }
            for k, v in por_tipo.items()
        },
        "top_productos": [
            {
                "producto_id": p["producto_id"],
                "nombre": p["nombre"],
                "cantidad": float(p["cantidad"]),
                "costo_total": float(p["costo_total"]),
            }
            for p in top_productos
        ],
    }


def merma_vs_produccion(db: Session, dias: int = 30) -> dict:
    """Calcula porcentaje de merma vs producción en el periodo."""
    from app.models.receta import OrdenProduccion, EstadoProduccion

    fecha_inicio = date.today() - timedelta(days=dias)
    hoy = date.today()

    # Total producido (órdenes completadas)
    ordenes = db.query(OrdenProduccion).filter(
        and_(
            OrdenProduccion.estado == EstadoProduccion.COMPLETADA,
            OrdenProduccion.fecha_fin.isnot(None),
            OrdenProduccion.fecha_fin >= datetime.combine(
                fecha_inicio, datetime.min.time(), tzinfo=timezone.utc
            ),
        )
    ).all()

    total_producido = sum(o.cantidad_producida for o in ordenes)

    # Total merma en el periodo
    total_merma = db.query(
        func.coalesce(func.sum(RegistroMerma.cantidad), Decimal("0"))
    ).filter(
        and_(
            RegistroMerma.fecha_merma >= fecha_inicio,
            RegistroMerma.fecha_merma <= hoy,
        )
    ).scalar() or Decimal("0")

    porcentaje = (
        float(total_merma / total_producido * 100)
        if total_producido > 0
        else 0.0
    )

    return {
        "dias": dias,
        "fecha_inicio": fecha_inicio.isoformat(),
        "fecha_fin": hoy.isoformat(),
        "total_producido": float(total_producido),
        "total_merma": float(total_merma),
        "porcentaje_merma": round(porcentaje, 2),
    }


def alertas_caducidad(db: Session, dias: int = 7) -> list[dict]:
    """Ingredientes y lotes que caducan en los próximos N días."""
    fecha_limite = date.today() + timedelta(days=dias)
    hoy = date.today()

    lotes = db.query(LoteIngrediente).filter(
        and_(
            LoteIngrediente.fecha_caducidad.isnot(None),
            LoteIngrediente.fecha_caducidad <= fecha_limite,
            LoteIngrediente.cantidad_disponible > 0,
        )
    ).order_by(LoteIngrediente.fecha_caducidad.asc()).all()

    alertas = []
    for lote in lotes:
        ingrediente = db.query(Ingrediente).filter(
            Ingrediente.id == lote.ingrediente_id
        ).first()

        dias_restantes = (lote.fecha_caducidad - hoy).days
        estado = "vencido" if dias_restantes < 0 else "por_vencer"

        alertas.append({
            "lote_id": lote.id,
            "ingrediente_id": lote.ingrediente_id,
            "ingrediente_nombre": ingrediente.nombre if ingrediente else "Desconocido",
            "numero_lote": lote.numero_lote,
            "fecha_caducidad": lote.fecha_caducidad.isoformat(),
            "cantidad_disponible": float(lote.cantidad_disponible),
            "costo_unitario": float(lote.costo_unitario),
            "valor_en_riesgo": float(lote.cantidad_disponible * lote.costo_unitario),
            "dias_restantes": dias_restantes,
            "estado": estado,
        })

    return alertas


def dashboard_merma(db: Session) -> dict:
    """Consolidado de merma para dashboard: hoy, semana, mes y top productos."""
    hoy = date.today()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)

    # Merma hoy
    merma_hoy = db.query(
        func.coalesce(func.sum(RegistroMerma.costo_total), Decimal("0"))
    ).filter(RegistroMerma.fecha_merma == hoy).scalar() or Decimal("0")

    merma_hoy_cantidad = db.query(
        func.coalesce(func.sum(RegistroMerma.cantidad), Decimal("0"))
    ).filter(RegistroMerma.fecha_merma == hoy).scalar() or Decimal("0")

    # Merma semana
    merma_semana = db.query(
        func.coalesce(func.sum(RegistroMerma.costo_total), Decimal("0"))
    ).filter(
        and_(
            RegistroMerma.fecha_merma >= inicio_semana,
            RegistroMerma.fecha_merma <= hoy,
        )
    ).scalar() or Decimal("0")

    # Merma mes
    merma_mes = db.query(
        func.coalesce(func.sum(RegistroMerma.costo_total), Decimal("0"))
    ).filter(
        and_(
            RegistroMerma.fecha_merma >= inicio_mes,
            RegistroMerma.fecha_merma <= hoy,
        )
    ).scalar() or Decimal("0")

    # Porcentaje vs producción (últimos 30 días)
    ratio = merma_vs_produccion(db, dias=30)

    # Top 5 productos con mayor merma en el mes
    registros_mes = db.query(RegistroMerma).filter(
        and_(
            RegistroMerma.fecha_merma >= inicio_mes,
            RegistroMerma.fecha_merma <= hoy,
            RegistroMerma.producto_id.isnot(None),
        )
    ).all()

    producto_merma: dict[int, dict] = {}
    for r in registros_mes:
        pid = r.producto_id
        if pid not in producto_merma:
            prod = db.query(Producto).filter(Producto.id == pid).first()
            producto_merma[pid] = {
                "producto_id": pid,
                "nombre": prod.nombre if prod else "Desconocido",
                "cantidad": Decimal("0"),
                "costo_total": Decimal("0"),
            }
        producto_merma[pid]["cantidad"] += r.cantidad
        producto_merma[pid]["costo_total"] += r.costo_total

    top_productos = sorted(
        producto_merma.values(), key=lambda x: x["costo_total"], reverse=True
    )[:5]

    return {
        "merma_hoy": {
            "costo_total": float(merma_hoy),
            "cantidad": float(merma_hoy_cantidad),
        },
        "merma_semana": float(merma_semana),
        "merma_mes": float(merma_mes),
        "pct_vs_produccion": ratio["porcentaje_merma"],
        "top_productos_merma": [
            {
                "producto_id": p["producto_id"],
                "nombre": p["nombre"],
                "cantidad": float(p["cantidad"]),
                "costo_total": float(p["costo_total"]),
            }
            for p in top_productos
        ],
    }
