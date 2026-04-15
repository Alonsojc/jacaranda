"""Rutas de reportes financieros e impuestos."""

import shutil
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import pdf_service
from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import reportes_service as svc
from app.services import alertas_service

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


@router.get("/ventas-por-hora")
def ventas_por_hora(
    dias: int = Query(default=7, le=30),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Ventas agrupadas por hora del día para heatmap."""
    return svc.reporte_ventas_por_hora(db, dias)


@router.get("/analisis-abc")
def analisis_abc(
    dias: int = Query(default=30, le=90),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Análisis ABC (Pareto 80/20) de productos por ingresos."""
    return svc.analisis_abc(db, dias)


@router.get("/dashboard-avanzado")
def dashboard_avanzado(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Dashboard avanzado: comparativos mensuales, proyección, clientes VIP, utilidad."""
    return svc.dashboard_avanzado(db)


@router.get("/punto-equilibrio")
def punto_equilibrio(
    dias: int = Query(default=30, le=90),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Punto de equilibrio (break-even analysis) de la panadería."""
    return svc.punto_de_equilibrio(db, dias)


@router.get("/flujo-efectivo")
def flujo_efectivo(
    meses: int = Query(default=3, le=12),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Proyección de flujo de efectivo a N meses."""
    return svc.flujo_efectivo_proyectado(db, meses)


@router.get("/alertas")
def alertas_consolidadas_endpoint(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Alertas consolidadas: stock bajo, caducidades, pedidos pendientes, merma."""
    data = alertas_service.alertas_consolidadas(db)
    total_criticas = sum(
        1 for a in data["stock_bajo"] if a["severidad"] == "critica"
    ) + sum(
        1 for a in data["caducidades"] if a["severidad"] == "critica"
    ) + sum(
        1 for a in data["pedidos_pendientes"] if a["severidad"] == "critica"
    )
    total_altas = sum(
        1 for a in data["stock_bajo"] if a["severidad"] == "alta"
    ) + sum(
        1 for a in data["caducidades"] if a["severidad"] == "alta"
    ) + sum(
        1 for a in data["pedidos_pendientes"] if a["severidad"] == "alta"
    )
    data["resumen"] = {
        "total_alertas": (
            len(data["stock_bajo"]) + len(data["caducidades"])
            + len(data["pedidos_pendientes"])
        ),
        "criticas": total_criticas,
        "altas": total_altas,
        "merma_porcentaje": data["merma_hoy"]["porcentaje_merma"],
    }
    return data


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


# ─── PDF Exports ──────────────────────────────────────────────────

@router.get("/ventas/pdf")
def reporte_ventas_pdf(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    """Descarga reporte de ventas en PDF."""
    data = svc.reporte_ventas_periodo(db, fecha_inicio, fecha_fin)
    buf = pdf_service.generar_reporte_ventas_pdf(data)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=ventas_{fecha_inicio}_{fecha_fin}.pdf"},
    )


@router.get("/impuestos/iva-mensual/pdf")
def reporte_iva_pdf(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    """Descarga reporte de IVA mensual en PDF."""
    data = svc.reporte_iva_mensual(db, mes, anio)
    buf = pdf_service.generar_reporte_iva_pdf(data)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=iva_{anio}_{mes:02d}.pdf"},
    )


@router.get("/impuestos/isr-provisional/pdf")
def reporte_isr_pdf(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(
        RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR
    )),
):
    """Descarga reporte de ISR provisional en PDF."""
    data = svc.reporte_isr_provisional(db, mes, anio)
    buf = pdf_service.generar_reporte_isr_pdf(data)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=isr_{anio}_{mes:02d}.pdf"},
    )
