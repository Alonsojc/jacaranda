"""Tests para bcrypt, refresh tokens y seguridad de autenticación."""

import pytest
from app.core.security import (
    verify_password, get_password_hash, needs_rehash,
    create_access_token, create_refresh_token, decode_access_token,
    JWTError,
)
import hashlib
import secrets


class TestBcryptMigration:
    """Tests para migración transparente SHA-256 → bcrypt."""

    def test_bcrypt_hash_and_verify(self):
        h = get_password_hash("micontraseña123")
        assert h.startswith("$2b$")
        assert verify_password("micontraseña123", h)
        assert not verify_password("otra", h)

    def test_legacy_sha256_verify(self):
        """Verifica que hashes legacy SHA-256 con salt siguen funcionando."""
        salt = secrets.token_hex(16)
        stored = hashlib.sha256((salt + "legacy123").encode()).hexdigest()
        legacy_hash = f"{salt}:{stored}"
        assert verify_password("legacy123", legacy_hash)
        assert not verify_password("wrong", legacy_hash)

    def test_needs_rehash_legacy(self):
        salt = secrets.token_hex(16)
        stored = hashlib.sha256((salt + "x").encode()).hexdigest()
        assert needs_rehash(f"{salt}:{stored}") is True

    def test_needs_rehash_bcrypt(self):
        h = get_password_hash("test")
        assert needs_rehash(h) is False

    def test_invalid_hash_format(self):
        assert not verify_password("x", "nocolon")


class TestRefreshTokens:
    """Tests para refresh tokens JWT."""

    def test_create_and_decode_refresh_token(self):
        token = create_refresh_token(data={"sub": 1, "rol": "admin"})
        payload = decode_access_token(token)
        assert payload["type"] == "refresh"
        assert payload["sub"] == 1
        assert payload["rol"] == "admin"

    def test_access_token_has_type(self):
        token = create_access_token(data={"sub": 2, "rol": "cajero"})
        payload = decode_access_token(token)
        assert payload["type"] == "access"

    def test_refresh_token_different_from_access(self):
        data = {"sub": 1, "rol": "admin"}
        access = create_access_token(data=data)
        refresh = create_refresh_token(data=data)
        assert access != refresh

    def test_invalid_token_raises(self):
        with pytest.raises(JWTError):
            decode_access_token("invalid.token.here")

    def test_tampered_token_raises(self):
        token = create_access_token(data={"sub": 1})
        parts = token.split(".")
        parts[1] = parts[1][::-1]  # tamper payload
        with pytest.raises(JWTError):
            decode_access_token(".".join(parts))


class TestRefreshEndpoint:
    """Tests del endpoint POST /auth/refresh."""

    def test_login_returns_refresh_token(self, client, admin_user):
        from app.api.routes.auth import _login_attempts
        _login_attempts.clear()
        resp = client.post("/api/v1/auth/login", json={
            "email": "admin@test.com", "password": "test1234"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["refresh_token"] is not None

    def test_refresh_returns_new_access_token(self, client, admin_user):
        from app.api.routes.auth import _login_attempts
        _login_attempts.clear()
        login = client.post("/api/v1/auth/login", json={
            "email": "admin@test.com", "password": "test1234"
        })
        refresh_token = login.json()["refresh_token"]
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_refresh_rejects_access_token(self, client, admin_user):
        from app.api.routes.auth import _login_attempts
        _login_attempts.clear()
        login = client.post("/api/v1/auth/login", json={
            "email": "admin@test.com", "password": "test1234"
        })
        access_token = login.json()["access_token"]
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": access_token
        })
        assert resp.status_code == 401

    def test_refresh_rejects_invalid_token(self, client):
        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid"
        })
        assert resp.status_code == 401

    def test_access_token_rejects_refresh_type(self, client, admin_user):
        """Asegurar que un refresh token no puede usarse como bearer."""
        from app.api.routes.auth import _login_attempts
        _login_attempts.clear()
        login = client.post("/api/v1/auth/login", json={
            "email": "admin@test.com", "password": "test1234"
        })
        refresh_token = login.json()["refresh_token"]
        resp = client.get("/api/v1/auth/me", headers={
            "Authorization": f"Bearer {refresh_token}"
        })
        assert resp.status_code == 401


class TestTransparentRehash:
    """Tests para migración transparente en login."""

    def test_legacy_user_gets_rehashed(self, client, db):
        from app.models.usuario import Usuario, RolUsuario
        import hashlib, secrets
        salt = secrets.token_hex(16)
        legacy_hash = f"{salt}:{hashlib.sha256((salt + 'legacy123').encode()).hexdigest()}"
        user = Usuario(
            nombre="Legacy User", email="legacy@test.com",
            hashed_password=legacy_hash, rol=RolUsuario.CAJERO,
        )
        db.add(user)
        db.commit()
        from app.api.routes.auth import _login_attempts
        _login_attempts.clear()
        resp = client.post("/api/v1/auth/login", json={
            "email": "legacy@test.com", "password": "legacy123"
        })
        assert resp.status_code == 200
        db.refresh(user)
        assert user.hashed_password.startswith("$2b$")
