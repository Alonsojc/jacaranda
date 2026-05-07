"""Rutas para ventas a cafeterías con crédito."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission
from app.models.cafeteria import EstadoCuentaCafeteria
from app.models.usuario import Usuario
from app.schemas.cafeteria import (
    CafeteriaVentaCreate,
    CafeteriaVentaResponse,
    PagoCafeteriaCreate,
)
from app.services import cafeteria_service as svc

router = APIRouter()


def _http_error(exc: ValueError) -> HTTPException:
    mensaje = str(exc)
    status = 404 if "no encontrada" in mensaje.lower() else 400
    return HTTPException(status_code=status, detail=mensaje)


@router.post("/ventas", response_model=CafeteriaVentaResponse, status_code=201)
def crear_venta_cafeteria(
    data: CafeteriaVentaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("cafeteria", "editar")),
):
    try:
        return svc.crear_venta(db, data, user.id)
    except ValueError as exc:
        raise _http_error(exc)


@router.get("/ventas", response_model=list[CafeteriaVentaResponse])
def listar_ventas_cafeteria(
    fecha_inicio: date | None = Query(default=None),
    fecha_fin: date | None = Query(default=None),
    estado: EstadoCuentaCafeteria | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    return svc.listar_ventas(db, fecha_inicio, fecha_fin, estado, limit)


@router.get("/ventas/{venta_id}", response_model=CafeteriaVentaResponse)
def obtener_venta_cafeteria(
    venta_id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    try:
        return svc.obtener_venta(db, venta_id)
    except ValueError as exc:
        raise _http_error(exc)


@router.post("/ventas/{venta_id}/pagos", response_model=CafeteriaVentaResponse)
def registrar_pago_cafeteria(
    venta_id: int,
    data: PagoCafeteriaCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("cafeteria", "editar")),
):
    try:
        return svc.registrar_pago(db, venta_id, data, user.id)
    except ValueError as exc:
        raise _http_error(exc)


@router.post("/ventas/{venta_id}/cancelar", response_model=CafeteriaVentaResponse)
def cancelar_venta_cafeteria(
    venta_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("cafeteria", "cancelar venta de cafetería")),
):
    try:
        return svc.cancelar_venta(db, venta_id, user.id)
    except ValueError as exc:
        raise _http_error(exc)


@router.get("/reportes/semanal")
def reporte_semanal_cafeteria(
    fecha: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    return svc.reporte_semanal(db, fecha)


@router.get("/reportes/mensual")
def reporte_mensual_cafeteria(
    mes: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    return svc.reporte_mensual(db, mes)
