"""Separate approval credentials from user login passwords."""

from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_password
from app.models.auditoria import ConfiguracionSeguridad
from app.models.usuario import Usuario
from app.services.auditoria_service import registrar_evento

CLAVE_CONFIG = "clave_autorizacion_hash"


def obtener_clave(db: Session) -> ConfiguracionSeguridad | None:
    return db.query(ConfiguracionSeguridad).filter(
        ConfiguracionSeguridad.clave == CLAVE_CONFIG,
    ).first()


def estado_clave(db: Session) -> dict:
    config = obtener_clave(db)
    return {"configurada": config is not None}


def verificar_clave(config: ConfiguracionSeguridad, password: str | None) -> bool:
    if not password or len(password.encode("utf-8")) > 72:
        return False
    try:
        return verify_password(password, config.valor)
    except (ValueError, TypeError):
        return False


def guardar_clave(db: Session, nueva_clave: str, actor: Usuario) -> dict:
    config = obtener_clave(db)
    configurada = config is not None
    hashed = get_password_hash(nueva_clave)
    if config is None:
        config = ConfiguracionSeguridad(
            clave=CLAVE_CONFIG,
            valor=hashed,
            descripcion="Clave para autorizar acciones sensibles; no sirve para iniciar sesion",
        )
        db.add(config)
    else:
        config.valor = hashed
    registrar_evento(
        db,
        usuario_id=actor.id,
        usuario_nombre=actor.nombre,
        accion="actualizar" if configurada else "crear",
        modulo="usuarios",
        entidad="clave_autorizacion",
        datos_anteriores={"configurada": configurada},
        datos_nuevos={"configurada": True},
        motivo="Configurar clave de autorizacion",
        commit=False,
    )
    db.commit()
    return {"configurada": True}
