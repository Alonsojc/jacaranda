"""Rutas de backup y restauración."""

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_admin_or_override, require_permission, require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import backup_service
from app.services.auditoria_service import registrar_evento

router = APIRouter()


class VerificarBackupRequest(BaseModel):
    filename: str | None = None


@router.post("/crear")
def crear_backup(
    user: Usuario = Depends(require_permission("backup", "editar")),
    db: Session = Depends(get_db),
):
    try:
        info = backup_service.crear_backup()
        registrar_evento(
            db,
            usuario_id=user.id,
            usuario_nombre=user.nombre,
            accion="crear",
            modulo="backup",
            entidad="backup",
            datos_nuevos={"filename": info["filename"], "size_bytes": info["size_bytes"]},
        )
        return info
    except (FileNotFoundError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/descargar")
def descargar_backup(
    user: Usuario = Depends(require_permission("backup", "editar")),
    db: Session = Depends(get_db),
):
    try:
        info = backup_service.obtener_ultimo_backup()
        registrar_evento(
            db,
            usuario_id=user.id,
            usuario_nombre=user.nombre,
            accion="descargar",
            modulo="backup",
            entidad="backup",
            datos_nuevos={"filename": info["filename"], "size_bytes": info["size_bytes"]},
        )
        return FileResponse(
            path=info["path"],
            filename=info["filename"],
            media_type="application/octet-stream",
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (OSError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restaurar")
async def restaurar_backup(
    file: UploadFile = File(...),
    user: Usuario = Depends(require_admin_or_override("backup", "restaurar backup")),
    db: Session = Depends(get_db),
):
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        result = backup_service.restaurar_backup(content, file.filename or "backup.db")
        registrar_evento(
            db,
            usuario_id=user.id,
            usuario_nombre=user.nombre,
            accion="restaurar",
            modulo="backup",
            entidad="backup",
            datos_nuevos={"filename": file.filename, "ok": result.get("ok")},
        )
        return result
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/verificar")
def verificar_backup(
    payload: VerificarBackupRequest | None = None,
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
    db: Session = Depends(get_db),
):
    try:
        result = backup_service.verificar_restauracion_backup(
            payload.filename if payload else None
        )
        registrar_evento(
            db,
            usuario_id=user.id,
            usuario_nombre=user.nombre,
            accion="verificar_restauracion",
            modulo="backup",
            entidad="backup",
            datos_nuevos={
                "filename": result.get("filename"),
                "restore_mode": result.get("restore_mode"),
                "ok": result.get("ok"),
            },
        )
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, RuntimeError, OSError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/listar")
def listar_backups(
    _user: Usuario = Depends(require_permission("backup", "editar")),
):
    try:
        return backup_service.listar_backups()
    except (OSError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estado")
def estado_backup(
    _user: Usuario = Depends(require_permission("backup", "editar")),
):
    return backup_service.estado_backup()


@router.delete("/{filename}")
def eliminar_backup(
    filename: str,
    user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
    db: Session = Depends(get_db),
    motivo: str = Header(..., alias="X-Admin-Override-Motivo", min_length=5),
):
    motivo_limpio = unquote(motivo or "").strip()
    if len(motivo_limpio) < 5:
        raise HTTPException(status_code=422, detail="El motivo debe tener al menos 5 caracteres")
    try:
        info = backup_service.eliminar_backup(filename)
        registrar_evento(
            db,
            usuario_id=user.id,
            usuario_nombre=user.nombre,
            accion="eliminar",
            modulo="backup",
            entidad="backup",
            datos_anteriores={"filename": info["filename"], "size_bytes": info["size_bytes"]},
            motivo=motivo_limpio,
        )
        return {"ok": True, "filename": info["filename"]}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ValueError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
