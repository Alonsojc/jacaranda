"""Rutas de facturación electrónica CFDI 4.0."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.usuario import Usuario
from app.schemas.facturacion import (
    CFDIGenerarRequest, CFDICancelRequest, CFDIResponse,
)
from app.services import cfdi_service as svc

router = APIRouter()


@router.post("/generar", response_model=CFDIResponse, status_code=201)
def generar_cfdi(
    data: CFDIGenerarRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    try:
        return svc.generar_cfdi(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=list[CFDIResponse])
def listar_cfdis(
    cliente_id: int | None = None,
    db: Session = Depends(get_db),
):
    return svc.listar_cfdis(db, cliente_id)


@router.get("/{id}", response_model=CFDIResponse)
def obtener_cfdi(id: int, db: Session = Depends(get_db)):
    try:
        return svc.obtener_cfdi(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{id}/xml")
def descargar_xml(id: int, db: Session = Depends(get_db)):
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
    _user: Usuario = Depends(get_current_user),
):
    try:
        return svc.cancelar_cfdi(db, id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
