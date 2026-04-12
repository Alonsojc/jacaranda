"""Rutas de gestión de inventario."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.usuario import Usuario
from app.schemas.inventario import (
    CategoriaCreate, CategoriaResponse,
    ProveedorCreate, ProveedorResponse,
    IngredienteCreate, IngredienteUpdate, IngredienteResponse,
    ProductoCreate, ProductoUpdate, ProductoResponse,
    MovimientoCreate, MovimientoResponse,
    LoteCreate, LoteResponse,
)
from app.services import inventario_service as svc

router = APIRouter()


# --- Categorías ---

@router.post("/categorias", response_model=CategoriaResponse, status_code=201)
def crear_categoria(data: CategoriaCreate, db: Session = Depends(get_db)):
    return svc.crear_categoria(db, data)


@router.get("/categorias", response_model=list[CategoriaResponse])
def listar_categorias(db: Session = Depends(get_db)):
    return svc.listar_categorias(db)


# --- Proveedores ---

@router.post("/proveedores", response_model=ProveedorResponse, status_code=201)
def crear_proveedor(data: ProveedorCreate, db: Session = Depends(get_db)):
    return svc.crear_proveedor(db, data)


@router.get("/proveedores", response_model=list[ProveedorResponse])
def listar_proveedores(db: Session = Depends(get_db)):
    return svc.listar_proveedores(db)


# --- Ingredientes ---

@router.post("/ingredientes", response_model=IngredienteResponse, status_code=201)
def crear_ingrediente(
    data: IngredienteCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.crear_ingrediente(db, data)


@router.get("/ingredientes", response_model=list[IngredienteResponse])
def listar_ingredientes(db: Session = Depends(get_db)):
    return svc.listar_ingredientes(db)


@router.get("/ingredientes/{id}", response_model=IngredienteResponse)
def obtener_ingrediente(id: int, db: Session = Depends(get_db)):
    try:
        return svc.obtener_ingrediente(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/ingredientes/{id}", response_model=IngredienteResponse)
def actualizar_ingrediente(id: int, data: IngredienteUpdate, db: Session = Depends(get_db)):
    try:
        return svc.actualizar_ingrediente(db, id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Productos ---

@router.post("/productos", response_model=ProductoResponse, status_code=201)
def crear_producto(
    data: ProductoCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    try:
        return svc.crear_producto(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/productos", response_model=list[ProductoResponse])
def listar_productos(db: Session = Depends(get_db)):
    return svc.listar_productos(db)


@router.get("/productos/{id}", response_model=ProductoResponse)
def obtener_producto(id: int, db: Session = Depends(get_db)):
    try:
        return svc.obtener_producto(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/productos/{id}", response_model=ProductoResponse)
def actualizar_producto(id: int, data: ProductoUpdate, db: Session = Depends(get_db)):
    try:
        return svc.actualizar_producto(db, id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Movimientos ---

@router.post("/movimientos", response_model=MovimientoResponse, status_code=201)
def registrar_movimiento(
    data: MovimientoCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        return svc.registrar_movimiento(db, data, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/movimientos", response_model=list[MovimientoResponse])
def listar_movimientos(
    ingrediente_id: int | None = None,
    producto_id: int | None = None,
    db: Session = Depends(get_db),
):
    return svc.listar_movimientos(db, ingrediente_id, producto_id)


# --- Lotes ---

@router.post("/lotes", response_model=LoteResponse, status_code=201)
def registrar_lote(data: LoteCreate, db: Session = Depends(get_db)):
    try:
        return svc.registrar_lote(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Alertas ---

@router.get("/alertas/stock-bajo")
def alertas_stock_bajo(db: Session = Depends(get_db)):
    return svc.alertas_stock_bajo(db)


@router.get("/alertas/por-caducar")
def alertas_caducidad(dias: int = Query(default=7), db: Session = Depends(get_db)):
    lotes = svc.ingredientes_por_caducar(db, dias)
    return [
        {
            "lote_id": l.id,
            "ingrediente_id": l.ingrediente_id,
            "numero_lote": l.numero_lote,
            "fecha_caducidad": l.fecha_caducidad.isoformat() if l.fecha_caducidad else None,
            "cantidad_disponible": float(l.cantidad_disponible),
        }
        for l in lotes
    ]
