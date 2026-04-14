"""Fixtures de pytest para testing."""

import pytest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.usuario import Usuario, RolUsuario

# Import all models so they register with Base.metadata
import app.models  # noqa: F401

# BD en archivo temporal para tests (in-memory no funciona bien con FastAPI lifespan)
TEST_DATABASE_URL = "sqlite:///./test_jacaranda.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    from main import app

    app.dependency_overrides[get_db] = override_get_db

    # Patch the engine and SessionLocal used by lifespan/_seed_admin
    with patch("main.engine", test_engine), \
         patch("main.SessionLocal", TestSessionLocal):
        with TestClient(app) as c:
            yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_user(db):
    user = Usuario(
        nombre="Admin Test",
        email="admin@test.com",
        hashed_password=get_password_hash("test1234"),
        rol=RolUsuario.ADMINISTRADOR,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_headers(client, admin_user):
    # Clear rate limit state between tests
    from app.api.routes.auth import _login_attempts
    _login_attempts.clear()

    response = client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "test1234",
    })
    assert response.status_code == 200, f"Login failed: {response.json()}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
