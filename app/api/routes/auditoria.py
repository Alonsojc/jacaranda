"""Rutas de auditoría y seguridad avanzada."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import auditoria_service as svc

router = APIRouter()

_admin = require_role(RolUsuario.ADMINISTRADOR)


@router.get("/")
def listar_eventos(
    request: Request,
    usuario_id: int | None = Query(None, description="Filtrar por ID de usuario"),
    modulo: str | None = Query(None, description="Filtrar por módulo"),
    accion: str | None = Query(None, description="Filtrar por tipo de acción"),
    fecha_inicio: datetime | None = Query(None, description="Fecha de inicio (ISO 8601)"),
    fecha_fin: datetime | None = Query(None, description="Fecha de fin (ISO 8601)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(_admin),
):
    """Lista eventos de auditoría con filtros opcionales."""
    eventos = svc.listar_eventos(
        db,
        usuario_id=usuario_id,
        modulo=modulo,
        accion=accion,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        skip=skip,
        limit=limit,
    )
    return [
        {
            "id": ev.id,
            "usuario_id": ev.usuario_id,
            "usuario_nombre": ev.usuario_nombre,
            "accion": ev.accion,
            "modulo": ev.modulo,
            "entidad": ev.entidad,
            "entidad_id": ev.entidad_id,
            "datos_anteriores": ev.datos_anteriores,
            "datos_nuevos": ev.datos_nuevos,
            "ip_address": ev.ip_address,
            "user_agent": ev.user_agent,
            "creado_en": ev.creado_en.isoformat() if ev.creado_en else None,
        }
        for ev in eventos
    ]


@router.get("/dashboard")
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(_admin),
):
    """Tablero resumen de auditoría."""
    return svc.dashboard_auditoria(db)


@router.get("/anomalias")
def anomalias(
    request: Request,
    dias: int = Query(7, ge=1, le=90, description="Días a analizar"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(_admin),
):
    """Detecta anomalías de seguridad en los últimos N días."""
    return svc.detectar_anomalias(db, dias=dias)


@router.get("/reporte")
def reporte_actividad(
    request: Request,
    fecha_inicio: datetime = Query(..., description="Fecha de inicio (ISO 8601)"),
    fecha_fin: datetime = Query(..., description="Fecha de fin (ISO 8601)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(_admin),
):
    """Genera reporte de actividad en un rango de fechas."""
    if fecha_fin <= fecha_inicio:
        raise HTTPException(
            status_code=400,
            detail="La fecha de fin debe ser posterior a la fecha de inicio",
        )
    return svc.reporte_actividad(db, fecha_inicio, fecha_fin)


@router.get("/actividad/{usuario_id}")
def actividad_usuario(
    usuario_id: int,
    request: Request,
    dias: int = Query(30, ge=1, le=365, description="Días de historial"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(_admin),
):
    """Resumen de actividad de un usuario específico."""
    return svc.actividad_usuario(db, usuario_id, dias=dias)


@router.get("/{evento_id}")
def obtener_evento(
    evento_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(_admin),
):
    """Detalle de un evento de auditoría."""
    evento = svc.obtener_evento(db, evento_id)
    if not evento:
        raise HTTPException(status_code=404, detail="Evento no encontrado")
    return {
        "id": evento.id,
        "usuario_id": evento.usuario_id,
        "usuario_nombre": evento.usuario_nombre,
        "accion": evento.accion,
        "modulo": evento.modulo,
        "entidad": evento.entidad,
        "entidad_id": evento.entidad_id,
        "datos_anteriores": evento.datos_anteriores,
        "datos_nuevos": evento.datos_nuevos,
        "ip_address": evento.ip_address,
        "user_agent": evento.user_agent,
        "creado_en": evento.creado_en.isoformat() if evento.creado_en else None,
    }


@router.post("/backup")
def crear_respaldo(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(_admin),
):
    """Crea un respaldo de la base de datos SQLite."""
    try:
        resultado = svc.respaldar_base_datos(db)
        return resultado
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
