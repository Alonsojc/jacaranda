"""Rutas de reportes financieros e impuestos."""

from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import reportes_service as svc

router = APIRouter()


@router.get("/dashboard")
def dashboard(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.dashboard_resumen(db)


@router.get("/ventas")
def reporte_ventas(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.reporte_ventas_periodo(db, fecha_inicio, fecha_fin)


@router.get("/productos-mas-vendidos")
def productos_mas_vendidos(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    return svc.reporte_productos_mas_vendidos(db, fecha_inicio, fecha_fin, limit)


@router.get("/impuestos/iva-mensual")
def reporte_iva(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    return svc.reporte_iva_mensual(db, mes, anio)


@router.get("/impuestos/isr-provisional")
def reporte_isr(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    return svc.reporte_isr_provisional(db, mes, anio)
