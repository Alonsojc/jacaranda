"""Schemas de usuarios y autenticación."""

from pydantic import BaseModel, EmailStr, Field
from datetime import datetime

from app.models.usuario import RolUsuario


class UsuarioCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., max_length=150)
    password: str = Field(..., min_length=8)
    rol: RolUsuario = RolUsuario.CAJERO


class UsuarioUpdate(BaseModel):
    nombre: str | None = None
    email: str | None = None
    rol: RolUsuario | None = None
    activo: bool | None = None


class UsuarioResponse(BaseModel):
    id: int
    nombre: str
    email: str
    rol: RolUsuario
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str
    password: str
