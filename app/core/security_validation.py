"""Validaciones de seguridad al arranque y utilidades de detección de archivos."""

import logging

from app.core.config import settings

logger = logging.getLogger("jacaranda.security")

# Claves de ejemplo conocidas que NO deben usarse en producción
_WEAK_SECRETS = {
    "cambiar-por-una-clave-secreta-segura-de-al-menos-32-caracteres",
    "secret",
    "change-me",
    "changeme",
    "supersecret",
    "mysecret",
    "default",
    "ci-test-secret-key-must-be-at-least-32-chars-long",
}


def validate_secret_key() -> None:
    """Valida SECRET_KEY al arranque. Aborta si es débil en modo producción."""
    key = settings.SECRET_KEY or ""
    if settings.DEBUG:
        if len(key) < 32:
            logger.warning("SECRET_KEY corta (%d chars) — OK en DEBUG", len(key))
        return

    if len(key) < 32:
        raise RuntimeError(
            "SECRET_KEY debe tener al menos 32 caracteres en producción. "
            "Genere una con: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
        )
    if key.lower() in _WEAK_SECRETS:
        raise RuntimeError(
            "SECRET_KEY es una clave de ejemplo conocida. Genere una nueva."
        )


# Magic bytes para validación de tipo real de archivo
_IMAGE_MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",  # debe verificarse también con 'WEBP' en offset 8
}

_PDF_MAGIC = b"%PDF-"


def detect_mime(data: bytes) -> str | None:
    """Detecta el MIME real por magic bytes. None si no reconocido."""
    if data.startswith(_PDF_MAGIC):
        return "application/pdf"
    for magic, mime in _IMAGE_MAGIC.items():
        if data.startswith(magic):
            if mime == "image/webp" and data[8:12] != b"WEBP":
                continue
            return mime
    return None


def is_image(data: bytes) -> bool:
    """True si los magic bytes corresponden a una imagen común."""
    mime = detect_mime(data)
    return mime is not None and mime.startswith("image/")
