"""Rutas de cumplimiento COFEPRIS y NOM-051."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.usuario import Usuario
from app.models.cofepris import AreaEstablecimiento
from app.schemas.cofepris import (
    TemperaturaCreate, TemperaturaResponse,
    LimpiezaCreate, LimpiezaResponse,
    InspeccionCreate, InspeccionResponse,
    ControlPlagasCreate, ControlPlagasResponse,
    EtiquetadoNOM051Response,
)
from app.services import cofepris_service as svc

router = APIRouter()


# --- Temperaturas ---

@router.post("/temperaturas", response_model=TemperaturaResponse, status_code=201)
def registrar_temperatura(
    data: TemperaturaCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.registrar_temperatura(db, data)


@router.get("/temperaturas", response_model=list[TemperaturaResponse])
def listar_temperaturas(
    area: AreaEstablecimiento | None = None,
    db: Session = Depends(get_db),
):
    return svc.listar_temperaturas(db, area)


@router.get("/temperaturas/alertas")
def alertas_temperatura(db: Session = Depends(get_db)):
    return svc.alertas_temperatura(db)


# --- Limpieza ---

@router.post("/limpieza", response_model=LimpiezaResponse, status_code=201)
def registrar_limpieza(
    data: LimpiezaCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.registrar_limpieza(db, data)


@router.get("/limpieza", response_model=list[LimpiezaResponse])
def listar_limpieza(db: Session = Depends(get_db)):
    return svc.listar_limpieza(db)


# --- Control de plagas ---

@router.post("/control-plagas", response_model=ControlPlagasResponse, status_code=201)
def registrar_control_plagas(
    data: ControlPlagasCreate,
    db: Session = Depends(get_db),
):
    return svc.registrar_control_plagas(db, data)


# --- Inspecciones sanitarias ---

@router.post("/inspecciones", response_model=InspeccionResponse, status_code=201)
def crear_inspeccion(
    data: InspeccionCreate,
    db: Session = Depends(get_db),
):
    return svc.crear_inspeccion(db, data)


@router.get("/inspecciones", response_model=list[InspeccionResponse])
def listar_inspecciones(db: Session = Depends(get_db)):
    return svc.listar_inspecciones(db)


# --- Reporte de cumplimiento ---

@router.get("/reporte-cumplimiento")
def reporte_cumplimiento(db: Session = Depends(get_db)):
    return svc.generar_reporte_cumplimiento(db)


# --- Licencias por vencer ---

@router.get("/licencias/por-vencer")
def licencias_por_vencer(dias: int = Query(default=30), db: Session = Depends(get_db)):
    licencias = svc.licencias_por_vencer(db, dias)
    return [
        {
            "id": l.id,
            "tipo": l.tipo,
            "numero": l.numero_licencia,
            "vencimiento": l.fecha_vencimiento.isoformat() if l.fecha_vencimiento else None,
        }
        for l in licencias
    ]


# --- Etiquetado NOM-051 ---

@router.get("/etiquetado/{producto_id}", response_model=EtiquetadoNOM051Response)
def etiquetado_nom051(producto_id: int, db: Session = Depends(get_db)):
    try:
        return svc.generar_etiquetado_nom051(db, producto_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
