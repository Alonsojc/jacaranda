"""Rutas de recetas, producción y optimización."""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission
from app.models.usuario import Usuario
from app.services.auditoria_service import registrar_evento
from app.schemas.receta import (
    RecetaCreate, RecetaUpdate, RecetaResponse, CostoRecetaResponse,
    HorneadoMasivoCreate, OrdenProduccionCreate, OrdenProduccionResponse,
)
from app.services import receta_service as svc
from app.services import produccion_service

router = APIRouter()


# --- Recetas ---

@router.post("/", response_model=RecetaResponse, status_code=201)
def crear_receta(
    data: RecetaCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "editar")),
):
    return svc.crear_receta(db, data)


@router.get("/", response_model=list[RecetaResponse])
def listar_recetas(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    return svc.listar_recetas(db)


@router.get("/inactivas", response_model=list[RecetaResponse])
def listar_recetas_inactivas(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("papelera", "ver")),
):
    return svc.listar_recetas(db, solo_activas=False, solo_inactivas=True)


@router.get("/{id}", response_model=RecetaResponse)
def obtener_receta(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    try:
        return svc.obtener_receta(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{id}", response_model=RecetaResponse)
def actualizar_receta(
    id: int,
    data: RecetaUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_admin_or_override("prod", "editar receta")),
):
    from app.models.receta import Receta, RecetaIngrediente
    receta = db.query(Receta).filter(Receta.id == id).first()
    if not receta:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    for field in ["nombre", "instrucciones", "rendimiento",
                  "tiempo_preparacion_min", "tiempo_horneado_min",
                  "temperatura_horneado_c", "activo"]:
        val = getattr(data, field, None)
        if val is not None:
            setattr(receta, field, val)
    if data.ingredientes is not None:
        db.query(RecetaIngrediente).filter(
            RecetaIngrediente.receta_id == id
        ).delete()
        for ri in data.ingredientes:
            db.add(RecetaIngrediente(
                receta_id=id,
                ingrediente_id=ri.ingrediente_id,
                cantidad=ri.cantidad,
                notas=ri.notas,
            ))
    db.commit()
    db.refresh(receta)
    return receta


@router.delete("/{id}")
def desactivar_receta(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_admin_or_override("prod", "desactivar receta")),
):
    from app.models.receta import Receta, OrdenProduccion, EstadoProduccion

    receta = db.query(Receta).filter(Receta.id == id).first()
    if not receta:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    orden_abierta = db.query(OrdenProduccion).filter(
        OrdenProduccion.receta_id == id,
        OrdenProduccion.estado.in_([
            EstadoProduccion.PLANIFICADA,
            EstadoProduccion.EN_PROCESO,
        ]),
    ).first()
    if orden_abierta:
        raise HTTPException(
            status_code=400,
            detail="No se puede desactivar: tiene órdenes de producción abiertas",
        )
    receta.activo = False
    db.commit()
    return {"ok": True}


@router.post("/{id}/reactivar", response_model=RecetaResponse)
def reactivar_receta(
    id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("papelera", "reactivar receta")),
):
    from app.models.receta import Receta

    receta = db.query(Receta).filter(Receta.id == id).first()
    if not receta:
        raise HTTPException(status_code=404, detail="Receta no encontrada")
    if receta.activo:
        raise HTTPException(status_code=400, detail="La receta ya está activa")
    receta.activo = True
    registrar_evento(
        db,
        usuario_id=user.id,
        usuario_nombre=user.nombre,
        accion="actualizar",
        modulo="papelera",
        entidad="receta",
        entidad_id=id,
        datos_anteriores={"activo": False},
        datos_nuevos={"activo": True, "accion": "reactivar receta"},
        commit=False,
    )
    db.commit()
    db.refresh(receta)
    return receta


@router.get("/{id}/costo")
def costo_receta(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    try:
        return svc.calcular_costo_receta(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{id}/disponibilidad")
def verificar_disponibilidad(
    id: int,
    lotes: Decimal = Query(default=Decimal("1")),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    faltantes = svc.verificar_disponibilidad_ingredientes(db, id, lotes)
    return {
        "disponible": len(faltantes) == 0,
        "faltantes": faltantes,
    }


# --- Órdenes de producción ---

@router.post("/produccion", response_model=OrdenProduccionResponse, status_code=201)
def crear_orden(
    data: OrdenProduccionCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "editar")),
):
    try:
        return svc.crear_orden_produccion(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/produccion", response_model=list[OrdenProduccionResponse])
def listar_ordenes(
    estado: str | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    from app.models.receta import EstadoProduccion
    est = None
    if estado:
        try:
            est = EstadoProduccion(estado)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Estado '{estado}' no válido")
    return svc.listar_ordenes(db, est)


@router.post("/produccion/{id}/iniciar", response_model=OrdenProduccionResponse)
def iniciar_produccion(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "editar")),
):
    try:
        return svc.iniciar_produccion(db, id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/produccion/{id}/completar", response_model=OrdenProduccionResponse)
def completar_produccion(
    id: int,
    cantidad_producida: Decimal = Query(...),
    cantidad_merma: Decimal = Query(default=Decimal("0")),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "editar")),
):
    try:
        return svc.completar_produccion(db, id, cantidad_producida, cantidad_merma)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/hornear-masivo")
def hornear_masivo(
    data: HorneadoMasivoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("prod", "editar")),
):
    """
    Registra varias tandas horneadas en una sola transacción.
    Primero valida ingredientes agregados para evitar producciones parciales.
    """
    from app.models.receta import Receta
    from app.models.inventario import Ingrediente, Producto, TipoMovimiento
    from app.schemas.inventario import MovimientoCreate
    from app.services.inventario_service import registrar_movimiento

    cantidades_por_receta: dict[int, int] = {}
    for item in data.items:
        cantidades_por_receta[item.receta_id] = (
            cantidades_por_receta.get(item.receta_id, 0) + item.cantidad
        )

    recetas = db.query(Receta).filter(
        Receta.id.in_(list(cantidades_por_receta.keys())),
        Receta.activo.is_(True),
    ).all()
    recetas_por_id = {receta.id: receta for receta in recetas}
    faltan_recetas = [
        rid for rid in cantidades_por_receta
        if rid not in recetas_por_id
    ]
    if faltan_recetas:
        raise HTTPException(
            status_code=404,
            detail=f"Recetas no encontradas o inactivas: {', '.join(map(str, faltan_recetas))}",
        )

    producto_ids = {receta.producto_id for receta in recetas if receta.producto_id}
    productos = db.query(Producto).filter(Producto.id.in_(list(producto_ids))).with_for_update().all()
    productos_por_id = {producto.id: producto for producto in productos}
    recetas_sin_producto = [
        receta.nombre for receta in recetas
        if receta.producto_id not in productos_por_id
    ]
    if recetas_sin_producto:
        raise HTTPException(
            status_code=400,
            detail="Recetas sin producto terminado: " + ", ".join(recetas_sin_producto),
        )

    requeridos_por_ingrediente: dict[int, Decimal] = {}
    for receta in recetas:
        cantidad = cantidades_por_receta[receta.id]
        for ri in receta.ingredientes:
            requeridos_por_ingrediente[ri.ingrediente_id] = (
                requeridos_por_ingrediente.get(ri.ingrediente_id, Decimal("0"))
                + (ri.cantidad * cantidad)
            )

    ingredientes_por_id: dict[int, Ingrediente] = {}
    if requeridos_por_ingrediente:
        ingredientes = db.query(Ingrediente).filter(
            Ingrediente.id.in_(list(requeridos_por_ingrediente.keys()))
        ).with_for_update().all()
        ingredientes_por_id = {ingrediente.id: ingrediente for ingrediente in ingredientes}

    faltantes = []
    for ingrediente_id, necesario in requeridos_por_ingrediente.items():
        ingrediente = ingredientes_por_id.get(ingrediente_id)
        if not ingrediente:
            faltantes.append({
                "ingrediente": f"ID {ingrediente_id}",
                "necesario": float(necesario),
                "disponible": 0,
            })
        elif ingrediente.stock_actual < necesario:
            faltantes.append({
                "ingrediente": ingrediente.nombre,
                "necesario": float(necesario),
                "disponible": float(ingrediente.stock_actual),
            })

    if faltantes:
        raise HTTPException(status_code=400, detail={
            "mensaje": "No hay suficientes ingredientes para el horneado del día",
            "faltantes": faltantes,
        })

    resultados = []
    try:
        for receta in recetas:
            cantidad = cantidades_por_receta[receta.id]
            for ri in receta.ingredientes:
                registrar_movimiento(
                    db,
                    MovimientoCreate(
                        tipo=TipoMovimiento.SALIDA_PRODUCCION,
                        ingrediente_id=ri.ingrediente_id,
                        cantidad=ri.cantidad * cantidad,
                        referencia=f"Horneado del día receta #{receta.id}",
                    ),
                    usuario_id=user.id,
                    commit=False,
                )

            piezas = int(receta.rendimiento or 1) * cantidad
            producto = productos_por_id[receta.producto_id]
            registrar_movimiento(
                db,
                MovimientoCreate(
                    tipo=TipoMovimiento.ENTRADA_PRODUCCION,
                    producto_id=producto.id,
                    cantidad=Decimal(str(piezas)),
                    referencia=f"Horneado del día receta #{receta.id}",
                ),
                usuario_id=user.id,
                commit=False,
            )
            resultados.append({
                "receta_id": receta.id,
                "receta": receta.nombre,
                "cantidad": cantidad,
                "piezas_producidas": piezas,
                "producto_id": producto.id,
                "producto": producto.nombre,
            })

        total_piezas = sum(r["piezas_producidas"] for r in resultados)
        registrar_evento(
            db,
            usuario_id=user.id,
            usuario_nombre=user.nombre,
            accion="crear",
            modulo="produccion",
            entidad="horneado_masivo",
            datos_nuevos={
                "total_recetas": len(resultados),
                "total_tandas": sum(cantidades_por_receta.values()),
                "total_piezas": total_piezas,
                "resultados": resultados,
            },
            commit=False,
        )
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    for resultado in resultados:
        producto = productos_por_id[resultado["producto_id"]]
        resultado["stock_producto"] = float(producto.stock_actual)

    return {
        "mensaje": "Horneado del día registrado",
        "total_recetas": len(resultados),
        "total_tandas": sum(cantidades_por_receta.values()),
        "total_piezas": sum(r["piezas_producidas"] for r in resultados),
        "resultados": resultados,
    }


@router.post("/{receta_id}/hornear")
def hornear(
    receta_id: int,
    cantidad: int = Query(1, description="Cuántas tandas hornear"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("prod", "editar")),
):
    """
    Hornear: descuenta ingredientes según receta y suma productos terminados.
    Ejemplo: hornear 2 tandas de Nutella = descuenta 2x ingredientes, suma 2x productos.
    """
    from app.models.receta import Receta, RecetaIngrediente
    from app.models.inventario import Ingrediente, Producto, TipoMovimiento
    from app.schemas.inventario import MovimientoCreate
    from app.services.inventario_service import registrar_movimiento

    receta = db.query(Receta).filter(Receta.id == receta_id).first()
    if not receta:
        raise HTTPException(status_code=404, detail="Receta no encontrada")

    # Verificar que hay suficientes ingredientes
    faltantes = []
    for ri in receta.ingredientes:
        ingrediente = db.query(Ingrediente).filter(Ingrediente.id == ri.ingrediente_id).first()
        necesario = ri.cantidad * cantidad
        if not ingrediente:
            faltantes.append({
                "ingrediente": f"ID {ri.ingrediente_id}",
                "necesario": float(necesario),
                "disponible": 0,
            })
        elif ingrediente.stock_actual < necesario:
            faltantes.append({
                "ingrediente": ingrediente.nombre,
                "necesario": float(necesario),
                "disponible": float(ingrediente.stock_actual),
            })

    if faltantes:
        raise HTTPException(status_code=400, detail={
            "mensaje": "No hay suficientes ingredientes",
            "faltantes": faltantes,
        })

    producto = db.query(Producto).filter(Producto.id == receta.producto_id).first()
    if not producto:
        raise HTTPException(status_code=400, detail="Producto de la receta no encontrado")

    # Descontar ingredientes y sumar producto terminado con trazabilidad.
    for ri in receta.ingredientes:
        registrar_movimiento(
            db,
            MovimientoCreate(
                tipo=TipoMovimiento.SALIDA_PRODUCCION,
                ingrediente_id=ri.ingrediente_id,
                cantidad=ri.cantidad * cantidad,
                referencia=f"Horneado receta #{receta.id}",
            ),
            usuario_id=user.id,
            commit=False,
        )

    piezas = int(receta.rendimiento or 1) * cantidad
    registrar_movimiento(
        db,
        MovimientoCreate(
            tipo=TipoMovimiento.ENTRADA_PRODUCCION,
            producto_id=producto.id,
            cantidad=Decimal(str(piezas)),
            referencia=f"Horneado receta #{receta.id}",
        ),
        usuario_id=user.id,
        commit=False,
    )

    db.commit()
    db.refresh(producto)

    return {
        "mensaje": f"Horneado: {cantidad}x {receta.nombre}",
        "piezas_producidas": piezas,
        "stock_producto": float(producto.stock_actual),
    }


# ─── Optimización de producción ───────────────────────────────────

@router.get("/produccion/prediccion-demanda")
def prediccion_demanda(
    dias: int = Query(7, ge=1, le=30, description="Días a predecir"),
    semanas_historial: int = Query(8, ge=2, le=52),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    """Predicción de demanda por producto basada en historial de ventas."""
    return produccion_service.predecir_demanda(db, dias, semanas_historial)


@router.get("/produccion/plan")
def plan_produccion(
    dias: int = Query(7, ge=1, le=30),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    """Plan de producción con recetas, lotes e ingredientes necesarios."""
    return produccion_service.generar_plan_produccion(db, dias)


@router.get("/produccion/eficiencia")
def analisis_eficiencia(
    dias: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    """Análisis de eficiencia: producción vs ventas, merma estimada."""
    return produccion_service.analisis_eficiencia(db, dias)


@router.get("/produccion/dashboard")
def dashboard_produccion(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("prod", "ver")),
):
    """Dashboard consolidado de producción."""
    return produccion_service.dashboard_produccion(db)
