"""Schemas de usuarios y autenticación."""

from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime

from app.models.usuario import RolUsuario


class UsuarioCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    rol: RolUsuario = RolUsuario.CAJERO


class UsuarioUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=100)
    email: EmailStr | None = None
    rol: RolUsuario | None = None
    activo: bool | None = None
    restablecer_permisos: bool = False

    @field_validator("nombre", "email", "rol", "activo", mode="before")
    @classmethod
    def no_null(cls, value):
        if value is None:
            raise ValueError("El campo no puede ser nulo")
        if isinstance(value, str):
            return value.strip()
        return value


class UsuarioResponse(BaseModel):
    id: int
    nombre: str
    email: str
    rol: RolUsuario
    permisos_modulos: dict
    activo: bool
    creado_en: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str
    password: str
