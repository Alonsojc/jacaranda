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


@router.get("/gastos-hoy")
def gastos_hoy(
    fecha: date | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.gastos_hoy(db, fecha)


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
    _user: Usuario = Depends(get_current_user),
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


@router.get("/margenes-producto")
def margenes_producto(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Margen de ganancia por producto (precio - costo)."""
    return svc.reporte_margenes_producto(db)


@router.get("/ventas-por-dia")
def ventas_por_dia(
    dias: int = Query(default=30, le=90),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Ventas diarias de los últimos N días para gráfica de tendencia."""
    return svc.reporte_ventas_por_dia(db, dias)


@router.get("/pronostico-produccion")
def pronostico_produccion(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Pronóstico de producción basado en ventas históricas."""
    try:
        return svc.pronostico_produccion(db)
    except Exception:
        return []


@router.get("/alertas-caducidad")
def alertas_caducidad(
    dias: int = Query(default=7, le=30),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Ingredientes con lotes por caducar."""
    return svc.alertas_caducidad(db, dias)


@router.get("/gastos-fijos-resumen")
def gastos_fijos_resumen(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Resumen de gastos fijos mensuales."""
    return svc.resumen_gastos_fijos(db)
