"""Rutas de KPIs y dashboard con datos para gráficas (Chart.js)."""

from datetime import date
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.services import kpi_service as svc
from app.services import excel_service

router = APIRouter()


@router.get("/dashboard")
def dashboard_kpis(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """Dashboard KPI consolidado."""
    return svc.dashboard_kpis(db)


@router.get("/ventas-por-hora")
def ventas_por_hora(
    fecha: date | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """Ventas agrupadas por hora del día (gráfica de barras)."""
    return svc.ventas_por_hora(db, fecha)


@router.get("/ventas-por-dia-semana")
def ventas_por_dia_semana(
    semanas: int = Query(4, ge=1, le=52),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """Promedio de ventas por día de la semana (gráfica de radar)."""
    return svc.ventas_por_dia_semana(db, semanas)


@router.get("/top-productos")
def top_productos(
    dias: int = Query(30, ge=1, le=365),
    limite: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """Top productos más vendidos (gráfica de barras/pie)."""
    return svc.top_productos(db, dias, limite)


@router.get("/tendencia-ventas")
def tendencia_ventas(
    dias: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """Tendencia de ventas diarias (gráfica de línea)."""
    return svc.tendencia_ventas(db, dias)


@router.get("/ticket-promedio")
def ticket_promedio(
    dias: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """Ticket promedio diario (gráfica de línea)."""
    return svc.ticket_promedio_diario(db, dias)


@router.get("/inventario")
def kpi_inventario(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """KPIs de inventario: stock bajo, valor, lotes por vencer."""
    return svc.kpi_inventario(db)


@router.get("/clientes")
def kpi_clientes(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """KPIs de clientes: total, nuevos, distribución de niveles."""
    return svc.kpi_clientes(db)


@router.get("/metodos-pago")
def metodos_pago(
    dias: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """Distribución de métodos de pago (gráfica de dona)."""
    return svc.distribucion_metodos_pago(db, dias)


# ─── Exportaciones ──────────────────────────────────────────────

@router.get("/exportar-excel")
def exportar_excel(
    dias: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("kpis", "ver")),
):
    """Descarga KPIs consolidados en Excel."""
    buf = excel_service.exportar_kpis(db, dias)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=kpis_dashboard.xlsx"},
    )
