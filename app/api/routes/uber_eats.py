"""Diagnóstico administrativo; no activa ni modifica tiendas de Uber Eats."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.usuario import RolUsuario
from app.services import uber_eats_service as svc


router = APIRouter(dependencies=[Depends(require_role(RolUsuario.ADMINISTRADOR))])


@router.get("/preparacion")
def preparacion(db: Session = Depends(get_db)):
    return {"conexion": svc.configuracion(), "catalogo": svc.preparar_catalogo(db)}


@router.post("/probar-conexion")
def probar_conexion():
    if not svc.configuracion()["puede_probar"]:
        raise HTTPException(status_code=409, detail="Falta configurar el entorno de pruebas de Uber Eats.")
    try:
        return svc.probar_conexion()
    except svc.UberEatsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
