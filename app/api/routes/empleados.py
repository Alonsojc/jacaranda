"""Rutas de gestión de empleados y nómina."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.usuario import Usuario, RolUsuario
from app.schemas.empleado import (
    EmpleadoCreate, EmpleadoUpdate, EmpleadoResponse,
    AsistenciaCreate, AsistenciaResponse,
    NominaCalculoRequest, NominaResponse,
)
from app.services import empleado_service as svc

router = APIRouter()


# --- Empleados ---

@router.post("/", response_model=EmpleadoResponse, status_code=201)
def crear_empleado(
    data: EmpleadoCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    return svc.crear_empleado(db, data)


@router.get("/", response_model=list[EmpleadoResponse])
def listar_empleados(
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.listar_empleados(db)


@router.get("/{id}", response_model=EmpleadoResponse)
def obtener_empleado(id: int, db: Session = Depends(get_db)):
    try:
        return svc.obtener_empleado(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/{id}", response_model=EmpleadoResponse)
def actualizar_empleado(
    id: int,
    data: EmpleadoUpdate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.GERENTE)),
):
    try:
        return svc.actualizar_empleado(db, id, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Asistencia ---

@router.post("/asistencia", response_model=AsistenciaResponse, status_code=201)
def registrar_asistencia(
    data: AsistenciaCreate,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(get_current_user),
):
    return svc.registrar_asistencia(db, data)


# --- Nómina ---

@router.post("/nomina/calcular", response_model=NominaResponse, status_code=201)
def calcular_nomina(
    data: NominaCalculoRequest,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR)),
):
    try:
        return svc.calcular_nomina(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/nomina", response_model=list[NominaResponse])
def listar_nominas(
    empleado_id: int | None = None,
    db: Session = Depends(get_db),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR, RolUsuario.CONTADOR)),
):
    return svc.listar_nominas(db, empleado_id)
