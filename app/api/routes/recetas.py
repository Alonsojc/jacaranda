"""Rutas de recetas y producción."""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.usuario import Usuario
from app.schemas.receta import (
    RecetaCreate, RecetaResponse, CostoRecetaResponse,
    OrdenProduccionCreate, OrdenProduccionResponse,
)
from app.services import receta_service as svc

router = APIRouter()


# --- Recetas ---

@router.post("/", response_model=RecetaResponse, status_code=201)
def crear_receta(data: RecetaCreate, db: Session = Depends(get_db)):
    return svc.crear_receta(db, data)


@router.get("/", response_model=list[RecetaResponse])
def listar_recetas(db: Session = Depends(get_db)):
    return svc.listar_recetas(db)


@router.get("/{id}", response_model=RecetaResponse)
def obtener_receta(id: int, db: Session = Depends(get_db)):
    try:
        return svc.obtener_receta(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{id}/costo")
def costo_receta(id: int, db: Session = Depends(get_db)):
    try:
        return svc.calcular_costo_receta(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{id}/disponibilidad")
def verificar_disponibilidad(
    id: int,
    lotes: Decimal = Query(default=Decimal("1")),
    db: Session = Depends(get_db),
):
    faltantes = svc.verificar_disponibilidad_ingredientes(db, id, lotes)
    return {
        "disponible": len(faltantes) == 0,
        "faltantes": faltantes,
    }


# --- Órdenes de producción ---

@router.post("/produccion", response_model=OrdenProduccionResponse, status_code=201)
def crear_orden(data: OrdenProduccionCreate, db: Session = Depends(get_db)):
    try:
        return svc.crear_orden_produccion(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/produccion", response_model=list[OrdenProduccionResponse])
def listar_ordenes(estado: str | None = None, db: Session = Depends(get_db)):
    from app.models.receta import EstadoProduccion
    est = None
    if estado:
        try:
            est = EstadoProduccion(estado)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Estado '{estado}' no válido")
    return svc.listar_ordenes(db, est)


@router.post("/produccion/{id}/iniciar", response_model=OrdenProduccionResponse)
def iniciar_produccion(id: int, db: Session = Depends(get_db)):
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
):
    try:
        return svc.completar_produccion(db, id, cantidad_producida, cantidad_merma)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{receta_id}/hornear")
def hornear(
    receta_id: int,
    cantidad: int = Query(1, description="Cuántas tandas hornear"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """
    Hornear: descuenta ingredientes según receta y suma productos terminados.
    Ejemplo: hornear 2 tandas de Nutella = descuenta 2x ingredientes, suma 2x productos.
    """
    from app.models.receta import Receta, RecetaIngrediente
    from app.models.inventario import Ingrediente, Producto

    receta = db.query(Receta).filter(Receta.id == receta_id).first()
    if not receta:
        raise HTTPException(status_code=404, detail="Receta no encontrada")

    # Verificar que hay suficientes ingredientes
    faltantes = []
    for ri in receta.ingredientes:
        ingrediente = db.query(Ingrediente).filter(Ingrediente.id == ri.ingrediente_id).first()
        necesario = ri.cantidad * cantidad
        if ingrediente and ingrediente.stock_actual < necesario:
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

    # Descontar ingredientes
    for ri in receta.ingredientes:
        ingrediente = db.query(Ingrediente).filter(Ingrediente.id == ri.ingrediente_id).first()
        if ingrediente:
            ingrediente.stock_actual -= ri.cantidad * cantidad

    # Sumar producto terminado
    piezas = 0
    producto = db.query(Producto).filter(Producto.id == receta.producto_id).first()
    if producto:
        piezas = int(receta.rendimiento or 1) * cantidad
        producto.stock_actual += Decimal(str(piezas))

    db.commit()

    return {
        "mensaje": f"Horneado: {cantidad}x {receta.nombre}",
        "piezas_producidas": piezas if producto else 0,
        "stock_producto": float(producto.stock_actual) if producto else 0,
    }
