"""Rutas de reportes financieros e impuestos."""

import shutil
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
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


@router.get("/mermas")
def reporte_mermas(
    dias: int = Query(default=30, le=90),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Reporte de mermas y desperdicio por producto/ingrediente."""
    return svc.reporte_mermas(db, dias)


@router.get("/kardex/{ingrediente_id}")
def kardex_ingrediente(
    ingrediente_id: int,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Kardex de un ingrediente: historial de movimientos con saldo."""
    try:
        return svc.kardex_ingrediente(db, ingrediente_id, limit)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/empleados-dashboard")
def dashboard_empleados(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Dashboard de empleados: cumpleaños, documentos por vencer."""
    return svc.dashboard_empleados(db)


@router.get("/backup")
def descargar_backup(
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    """Descarga backup de la base de datos SQLite (solo admin)."""
    db_url = settings.DATABASE_URL
    if not db_url.startswith("sqlite"):
        raise HTTPException(status_code=400, detail="Backup solo disponible para SQLite")
    db_path = db_url.replace("sqlite:///", "")
    src = Path(db_path)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Base de datos no encontrada")
    backup_path = Path(f"/tmp/jacaranda_backup_{date.today().isoformat()}.db")
    shutil.copy2(str(src), str(backup_path))
    return FileResponse(
        path=str(backup_path),
        filename=f"jacaranda_backup_{date.today().isoformat()}.db",
        media_type="application/octet-stream",
    )
