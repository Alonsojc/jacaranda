"""Rutas de facturación electrónica CFDI 4.0 con timbrado PAC."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.models.usuario import Usuario
from app.schemas.facturacion import (
    CFDIGenerarRequest, CFDICancelRequest, CFDIResponse,
)
from app.services import cfdi_service as svc
from app.services import pac_service

router = APIRouter()


@router.post("/generar", response_model=CFDIResponse, status_code=201)
def generar_cfdi(
    data: CFDIGenerarRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "editar")),
):
    try:
        return svc.generar_cfdi(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=list[CFDIResponse])
def listar_cfdis(
    cliente_id: int | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    return svc.listar_cfdis(db, cliente_id)


@router.get("/{id}", response_model=CFDIResponse)
def obtener_cfdi(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    try:
        return svc.obtener_cfdi(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{id}/xml")
def descargar_xml(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    try:
        cfdi = svc.obtener_cfdi(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not cfdi.xml_generado:
        raise HTTPException(status_code=404, detail="XML no disponible")

    return Response(
        content=cfdi.xml_generado,
        media_type="application/xml",
        headers={
            "Content-Disposition": f"attachment; filename=CFDI_{cfdi.serie}{cfdi.folio}.xml"
        },
    )


@router.post("/{id}/cancelar", response_model=CFDIResponse)
def cancelar_cfdi(
    id: int,
    data: CFDICancelRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "editar")),
):
    try:
        return svc.cancelar_cfdi(db, id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── PAC: Timbrado y cancelación ante SAT ─────────────────────────


@router.post("/{id}/timbrar")
def timbrar_cfdi(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "editar")),
):
    """Envía el CFDI al PAC para timbrado (sandbox)."""
    try:
        return pac_service.timbrar_cfdi(db, id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class CancelacionSATRequest(BaseModel):
    motivo: str
    uuid_sustitucion: str | None = None


@router.post("/{id}/cancelar-sat")
def cancelar_cfdi_sat(
    id: int,
    data: CancelacionSATRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "editar")),
):
    """Cancela un CFDI ante el SAT vía PAC (sandbox)."""
    try:
        return pac_service.cancelar_cfdi_sat(db, id, data.motivo, data.uuid_sustitucion)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{id}/estatus-sat")
def consultar_estatus_sat(
    id: int,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Consulta estatus del CFDI ante el SAT."""
    try:
        return pac_service.consultar_estatus_sat(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


class DescargaMasivaRequest(BaseModel):
    cfdi_ids: list[int]


@router.post("/xml/descarga-masiva")
def descarga_masiva_xml(
    data: DescargaMasivaRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_permission("fiscal", "ver")),
):
    """Descarga múltiples XMLs de CFDIs."""
    return pac_service.descargar_xml_masivo(db, data.cfdi_ids)
