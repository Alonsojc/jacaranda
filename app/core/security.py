"""Seguridad: hashing de contraseñas con bcrypt y tokens JWT."""

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import secrets

import bcrypt

from app.core.config import settings

ALGORITHM = "HS256"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica contraseña. Soporta bcrypt y legacy SHA-256 con salt."""
    if hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$"):
        # bcrypt hash
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    # Legacy SHA-256 con salt (migración transparente)
    if ":" not in hashed_password:
        return False
    salt, stored_hash = hashed_password.split(":", 1)
    computed = hashlib.sha256((salt + plain_password).encode()).hexdigest()
    return hmac.compare_digest(computed, stored_hash)


def get_password_hash(password: str) -> str:
    """Genera hash de contraseña con bcrypt."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    ).decode("utf-8")


def needs_rehash(hashed_password: str) -> bool:
    """True si el hash es legacy SHA-256 y necesita migrar a bcrypt."""
    return not (
        hashed_password.startswith("$2b$")
        or hashed_password.startswith("$2a$")
    )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Crea JWT token con HMAC-SHA256."""
    to_encode = data.copy()
    to_encode["type"] = "access"
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = int(expire.timestamp())

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps(to_encode).encode())
    message = f"{header}.{payload}"
    signature = hmac.new(
        settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256
    ).digest()
    sig_encoded = _b64url_encode(signature)
    return f"{message}.{sig_encoded}"


def create_refresh_token(data: dict) -> str:
    """Crea refresh token con expiración de 7 días."""
    to_encode = data.copy()
    to_encode["type"] = "refresh"
    expire = datetime.now(timezone.utc) + timedelta(days=7)
    to_encode["exp"] = int(expire.timestamp())

    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps(to_encode).encode())
    message = f"{header}.{payload}"
    signature = hmac.new(
        settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256
    ).digest()
    sig_encoded = _b64url_encode(signature)
    return f"{message}.{sig_encoded}"


class JWTError(Exception):
    pass


def decode_access_token(token: str) -> dict:
    """Decodifica y verifica JWT token."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise JWTError("Token inválido")

        header_b64, payload_b64, sig_b64 = parts
        message = f"{header_b64}.{payload_b64}"

        # Verificar firma
        expected_sig = hmac.new(
            settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256
        ).digest()
        actual_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise JWTError("Firma inválida")

        # Decodificar payload
        payload = json.loads(_b64url_decode(payload_b64))

        # Verificar expiración
        exp = payload.get("exp")
        if exp and datetime.now(timezone.utc).timestamp() > exp:
            raise JWTError("Token expirado")

        return payload
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        raise JWTError(f"Token inválido: {e}")
