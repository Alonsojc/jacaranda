"""Modelo de usuarios del sistema."""

from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, Text, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column
import enum
import json

from app.core.database import Base


class RolUsuario(str, enum.Enum):
    ADMINISTRADOR = "administrador"
    GERENTE = "gerente"
    CAJERO = "cajero"
    PANADERO = "panadero"
    ALMACENISTA = "almacenista"
    CONTADOR = "contador"


# Módulos del sistema con permisos configurables
MODULOS_DISPONIBLES = [
    "dash", "pos", "ped", "inv", "corte", "rep", "listas", "cofepris", "usuarios",
]


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    rol: Mapped[RolUsuario] = mapped_column(SAEnum(RolUsuario), default=RolUsuario.CAJERO)
    # JSON: {"modulo": "ver"|"editar"|"oculto"} — null = defaults by role
    _permisos_modulos: Mapped[str | None] = mapped_column("permisos_modulos", Text, default=None)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    @property
    def permisos_modulos(self) -> dict:
        if self._permisos_modulos:
            return json.loads(self._permisos_modulos)
        # Defaults por rol
        if self.rol == RolUsuario.ADMINISTRADOR:
            return {m: "editar" for m in MODULOS_DISPONIBLES}
        elif self.rol in (RolUsuario.GERENTE,):
            return {m: "editar" for m in MODULOS_DISPONIBLES if m != "usuarios"}
        elif self.rol == RolUsuario.CAJERO:
            return {"dash": "ver", "pos": "editar", "ped": "ver", "corte": "ver"}
        elif self.rol == RolUsuario.CONTADOR:
            return {"dash": "ver", "rep": "editar", "corte": "ver"}
        elif self.rol == RolUsuario.PANADERO:
            return {"dash": "ver", "inv": "editar", "ped": "ver"}
        elif self.rol == RolUsuario.ALMACENISTA:
            return {"dash": "ver", "inv": "editar", "listas": "ver"}
        return {"dash": "ver", "pos": "ver"}

    @permisos_modulos.setter
    def permisos_modulos(self, value: dict | None):
        self._permisos_modulos = json.dumps(value) if value else None
