"""Fixtures de pytest para testing."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.core.security import get_password_hash
from app.models.usuario import Usuario, RolUsuario
from main import app

# BD en memoria para tests
TEST_DATABASE_URL = "sqlite:///./test_jacaranda.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
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
    response = client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "test1234",
    })
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
