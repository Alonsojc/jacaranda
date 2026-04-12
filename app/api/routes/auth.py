"""Rutas de autenticación."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioResponse, Token, LoginRequest
from app.services.auth_service import crear_usuario, autenticar_usuario, generar_token

router = APIRouter()


@router.post("/registro", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def registro(data: UsuarioCreate, db: Session = Depends(get_db)):
    try:
        return crear_usuario(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=Token)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    usuario = autenticar_usuario(db, data.email, data.password)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
        )
    token = generar_token(usuario)
    return Token(access_token=token)


@router.get("/me", response_model=UsuarioResponse)
def perfil(current_user: Usuario = Depends(get_current_user)):
    return current_user
