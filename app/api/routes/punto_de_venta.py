"""Rutas de punto de venta (POS)."""

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.usuario import Usuario
from app.schemas.venta import (
    VentaCreate, VentaResponse, TicketResponse, CorteCajaCreate, CorteCajaResponse,
)
from app.services import venta_service as svc

router = APIRouter()


@router.post("/ventas", response_model=VentaResponse, status_code=201)
def crear_venta(
    data: VentaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        return svc.procesar_venta(db, data, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/ventas", response_model=list[VentaResponse])
def listar_ventas(
    fecha_inicio: date | None = None,
    fecha_fin: date | None = None,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
):
    return svc.listar_ventas(db, fecha_inicio, fecha_fin, limit)


@router.get("/ventas/{id}", response_model=VentaResponse)
def obtener_venta(id: int, db: Session = Depends(get_db)):
    try:
        return svc.obtener_venta(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/ventas/{id}/ticket")
def obtener_ticket(id: int, db: Session = Depends(get_db)):
    try:
        return svc.generar_ticket(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/ventas/{id}/cancelar", response_model=VentaResponse)
def cancelar_venta(
    id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    try:
        return svc.cancelar_venta(db, id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Corte de caja ---

@router.post("/corte-caja", response_model=CorteCajaResponse, status_code=201)
def realizar_corte(
    data: CorteCajaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return svc.realizar_corte_caja(db, data, user.id)
