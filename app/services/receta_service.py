"""
Servicio de recetas y producción.
Costeo de productos, planificación de producción, descuento de ingredientes.
"""

from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.receta import Receta, RecetaIngrediente, OrdenProduccion, EstadoProduccion
from app.models.inventario import Ingrediente, Producto, TipoMovimiento
from app.schemas.receta import RecetaCreate, OrdenProduccionCreate
from app.schemas.inventario import MovimientoCreate
from app.services.inventario_service import registrar_movimiento


def crear_receta(db: Session, data: RecetaCreate) -> Receta:
    receta = Receta(
        producto_id=data.producto_id,
        nombre=data.nombre,
        descripcion=data.descripcion,
        instrucciones=data.instrucciones,
        rendimiento=data.rendimiento,
        tiempo_preparacion_min=data.tiempo_preparacion_min,
        tiempo_horneado_min=data.tiempo_horneado_min,
        temperatura_horneado_c=data.temperatura_horneado_c,
    )
    db.add(receta)
    db.flush()

    for ing_data in data.ingredientes:
        ri = RecetaIngrediente(
            receta_id=receta.id,
            ingrediente_id=ing_data.ingrediente_id,
            cantidad=ing_data.cantidad,
            notas=ing_data.notas,
        )
        db.add(ri)

    db.commit()
    db.refresh(receta)
    return receta


def obtener_receta(db: Session, id: int) -> Receta:
    receta = db.query(Receta).filter(Receta.id == id).first()
    if not receta:
        raise ValueError("Receta no encontrada")
    return receta


def listar_recetas(db: Session):
    return db.query(Receta).filter(Receta.activo.is_(True)).all()


def calcular_costo_receta(db: Session, receta_id: int) -> dict:
    """Calcula el costo total de una receta basado en los ingredientes actuales."""
    receta = obtener_receta(db, receta_id)
    desglose = []
    costo_total = Decimal("0")

    for ri in receta.ingredientes:
        ingrediente = db.query(Ingrediente).filter(
            Ingrediente.id == ri.ingrediente_id
        ).first()
        if not ingrediente:
            continue
        costo = ri.cantidad * ingrediente.costo_unitario
        costo_total += costo
        desglose.append({
            "ingrediente": ingrediente.nombre,
            "cantidad": float(ri.cantidad),
            "unidad": ingrediente.unidad_medida.value,
            "costo_unitario": float(ingrediente.costo_unitario),
            "costo_total": float(costo),
        })

    costo_por_pieza = (
        costo_total / receta.rendimiento if receta.rendimiento > 0 else Decimal("0")
    )

    return {
        "receta_id": receta.id,
        "nombre": receta.nombre,
        "rendimiento": float(receta.rendimiento),
        "costo_total_ingredientes": float(costo_total),
        "costo_por_pieza": float(costo_por_pieza),
        "desglose": desglose,
    }


def verificar_disponibilidad_ingredientes(
    db: Session, receta_id: int, lotes: Decimal = Decimal("1"),
) -> list[dict]:
    """Verifica si hay suficientes ingredientes para producir N lotes."""
    receta = obtener_receta(db, receta_id)
    faltantes = []

    for ri in receta.ingredientes:
        ingrediente = db.query(Ingrediente).filter(
            Ingrediente.id == ri.ingrediente_id
        ).first()
        if not ingrediente:
            faltantes.append({
                "ingrediente_id": ri.ingrediente_id,
                "mensaje": "Ingrediente no encontrado",
            })
            continue

        requerido = ri.cantidad * lotes
        if ingrediente.stock_actual < requerido:
            faltantes.append({
                "ingrediente_id": ingrediente.id,
                "ingrediente": ingrediente.nombre,
                "requerido": float(requerido),
                "disponible": float(ingrediente.stock_actual),
                "faltante": float(requerido - ingrediente.stock_actual),
                "unidad": ingrediente.unidad_medida.value,
            })

    return faltantes


# --- Órdenes de producción ---

def crear_orden_produccion(db: Session, data: OrdenProduccionCreate) -> OrdenProduccion:
    # Verificar disponibilidad
    faltantes = verificar_disponibilidad_ingredientes(
        db, data.receta_id, data.cantidad_lotes
    )
    if faltantes:
        nombres = [f["ingrediente"] for f in faltantes if "ingrediente" in f]
        raise ValueError(
            f"Ingredientes insuficientes: {', '.join(nombres)}"
        )

    orden = OrdenProduccion(
        receta_id=data.receta_id,
        cantidad_lotes=data.cantidad_lotes,
        fecha_programada=data.fecha_programada,
        responsable_id=data.responsable_id,
        notas=data.notas,
    )
    db.add(orden)
    db.commit()
    db.refresh(orden)
    return orden


def iniciar_produccion(db: Session, orden_id: int) -> OrdenProduccion:
    orden = db.query(OrdenProduccion).filter(OrdenProduccion.id == orden_id).first()
    if not orden:
        raise ValueError("Orden de producción no encontrada")
    if orden.estado != EstadoProduccion.PLANIFICADA:
        raise ValueError("Solo se pueden iniciar órdenes planificadas")

    orden.estado = EstadoProduccion.EN_PROCESO
    orden.fecha_inicio = datetime.now(timezone.utc)

    # Descontar ingredientes del inventario
    receta = obtener_receta(db, orden.receta_id)
    for ri in receta.ingredientes:
        cantidad_total = ri.cantidad * orden.cantidad_lotes
        mov = MovimientoCreate(
            tipo=TipoMovimiento.SALIDA_PRODUCCION,
            ingrediente_id=ri.ingrediente_id,
            cantidad=cantidad_total,
            referencia=f"Orden producción #{orden.id}",
        )
        registrar_movimiento(db, mov)

    db.commit()
    db.refresh(orden)
    return orden


def completar_produccion(
    db: Session, orden_id: int, cantidad_producida: Decimal, cantidad_merma: Decimal = Decimal("0"),
) -> OrdenProduccion:
    orden = db.query(OrdenProduccion).filter(OrdenProduccion.id == orden_id).first()
    if not orden:
        raise ValueError("Orden de producción no encontrada")
    if orden.estado != EstadoProduccion.EN_PROCESO:
        raise ValueError("Solo se pueden completar órdenes en proceso")

    orden.estado = EstadoProduccion.COMPLETADA
    orden.cantidad_producida = cantidad_producida
    orden.cantidad_merma = cantidad_merma
    orden.fecha_fin = datetime.now(timezone.utc)

    # Agregar productos al inventario
    receta = obtener_receta(db, orden.receta_id)
    mov = MovimientoCreate(
        tipo=TipoMovimiento.ENTRADA_PRODUCCION,
        producto_id=receta.producto_id,
        cantidad=cantidad_producida,
        referencia=f"Orden producción #{orden.id}",
    )
    registrar_movimiento(db, mov)

    # Registrar merma si existe
    if cantidad_merma > 0:
        mov_merma = MovimientoCreate(
            tipo=TipoMovimiento.SALIDA_MERMA,
            producto_id=receta.producto_id,
            cantidad=cantidad_merma,
            referencia=f"Merma orden #{orden.id}",
        )
        registrar_movimiento(db, mov_merma)

    db.commit()
    db.refresh(orden)
    return orden


def listar_ordenes(db: Session, estado: EstadoProduccion | None = None, skip: int = 0, limit: int = 100):
    query = db.query(OrdenProduccion)
    if estado:
        query = query.filter(OrdenProduccion.estado == estado)
    return query.order_by(OrdenProduccion.fecha_programada.desc()).offset(skip).limit(limit).all()
