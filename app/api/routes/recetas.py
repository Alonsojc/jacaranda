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
