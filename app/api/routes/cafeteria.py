"""Rutas para ventas a cafeterías con crédito."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission
from app.models.cafeteria import EstadoCuentaCafeteria
from app.models.usuario import Usuario
from app.schemas.cafeteria import (
    CafeteriaClienteCreate,
    CafeteriaFiltroClienteResponse,
    CafeteriaClienteResponse,
    CafeteriaClienteUpdate,
    CafeteriaVentaCreate,
    CafeteriaVentaResponse,
    PagoCafeteriaCreate,
    FechaEntregaCafeteriaUpdate,
)
from app.services import cafeteria_service as svc
from app.services import cafeteria_export_service as exports

router = APIRouter()


class MotivoCriticoRequest(BaseModel):
    motivo: str = Field(..., min_length=5, max_length=300)


def _http_error(exc: ValueError) -> HTTPException:
    mensaje = str(exc)
    status = 404 if "no encontrada" in mensaje.lower() else 400
    return HTTPException(status_code=status, detail=mensaje)


@router.get("/clientes", response_model=list[CafeteriaClienteResponse])
def listar_clientes_cafeteria(
    q: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    return svc.listar_cafeterias(db, q=q, limit=limit)


@router.post("/clientes", response_model=CafeteriaClienteResponse, status_code=201)
def crear_cliente_cafeteria(
    data: CafeteriaClienteCreate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("cafeteria", "editar")),
):
    try:
        return svc.crear_cafeteria(db, data, user.id)
    except ValueError as exc:
        raise _http_error(exc)


@router.put("/clientes/{cliente_id}", response_model=CafeteriaClienteResponse)
def actualizar_cliente_cafeteria(
    cliente_id: int,
    data: CafeteriaClienteUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("cafeteria", "editar")),
):
    try:
        return svc.actualizar_cafeteria(db, cliente_id, data, user.id)
    except ValueError as exc:
        raise _http_error(exc)


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
    offset: int = Query(default=0, ge=0),
    cafeteria_id: int | None = Query(default=None, gt=0),
    cafeteria_nombre: str | None = Query(default=None, min_length=1, max_length=200),
    pendientes: bool = Query(default=False),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    try:
        return svc.listar_ventas(db, fecha_inicio, fecha_fin, estado, limit,
                                cafeteria_id=cafeteria_id, cafeteria_nombre=cafeteria_nombre,
                                pendientes=pendientes, offset=offset)
    except ValueError as exc:
        raise _http_error(exc)


@router.get("/cobranza/clientes", response_model=list[CafeteriaFiltroClienteResponse])
def clientes_cobranza(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    return svc.clientes_cobranza(db)


@router.get("/cobranza/resumen")
def resumen_cobranza(
    cafeteria_id: int | None = Query(default=None, gt=0),
    cafeteria_nombre: str | None = Query(default=None, min_length=1, max_length=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    try:
        return svc.resumen_cobranza(db, cafeteria_id, cafeteria_nombre)
    except ValueError as exc:
        raise _http_error(exc)


@router.get("/estado-cuenta/pdf")
def estado_cuenta_pdf(
    cafeteria_id: int | None = Query(default=None, gt=0),
    cafeteria_nombre: str | None = Query(default=None, min_length=1, max_length=200),
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    try:
        buf = exports.generar_estado_cuenta_pdf(db, cafeteria_id, cafeteria_nombre)
    except ValueError as exc:
        raise _http_error(exc)
    return StreamingResponse(buf, media_type="application/pdf", headers={
        "Content-Disposition": "attachment; filename=estado_cuenta_cafeteria.pdf",
    })


@router.get("/historial/excel")
def historial_excel(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("cafeteria", "ver")),
):
    return StreamingResponse(
        exports.exportar_historial_excel(db),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=cafeterias_historial_completo.xlsx"},
    )


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


@router.put("/ventas/{venta_id}/entrega", response_model=CafeteriaVentaResponse)
def actualizar_fecha_entrega(
    venta_id: int,
    data: FechaEntregaCafeteriaUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_permission("cafeteria", "editar")),
):
    try:
        return svc.actualizar_fecha_entrega(db, venta_id, data, user.id)
    except ValueError as exc:
        raise _http_error(exc)


@router.post("/ventas/{venta_id}/cancelar", response_model=CafeteriaVentaResponse)
def cancelar_venta_cafeteria(
    venta_id: int,
    data: MotivoCriticoRequest,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin_or_override("cafeteria", "cancelar venta de cafetería")),
):
    try:
        return svc.cancelar_venta(db, venta_id, user.id, data.motivo.strip())
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
