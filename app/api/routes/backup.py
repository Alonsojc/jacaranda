"""Rutas de backup y restauración."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pathlib import Path

from app.core.dependencies import require_role
from app.models.usuario import Usuario, RolUsuario
from app.services import backup_service

router = APIRouter()


@router.post("/crear")
def crear_backup(
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    try:
        return backup_service.crear_backup()
    except (FileNotFoundError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/descargar")
def descargar_backup(
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    try:
        info = backup_service.crear_backup()
        return FileResponse(
            path=info["path"],
            filename=info["filename"],
            media_type="application/octet-stream",
        )
    except (FileNotFoundError, RuntimeError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restaurar")
async def restaurar_backup(
    file: UploadFile = File(...),
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        return backup_service.restaurar_backup(content, file.filename or "backup.db")
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/listar")
def listar_backups(
    _user: Usuario = Depends(require_role(RolUsuario.ADMINISTRADOR)),
):
    return backup_service.listar_backups()
