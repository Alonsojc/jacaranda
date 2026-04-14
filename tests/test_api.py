"""Tests de integración para la API."""


class TestAuth:
    def test_login(self, client, admin_user):
        response = client.post("/api/v1/auth/login", json={
            "email": "admin@test.com",
            "password": "test1234",
        })
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_login_credenciales_invalidas(self, client):
        response = client.post("/api/v1/auth/login", json={
            "email": "noexiste@test.com",
            "password": "wrong",
        })
        assert response.status_code == 401

    def test_perfil(self, client, auth_headers):
        response = client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["email"] == "admin@test.com"

    def test_crear_usuario_admin(self, client, auth_headers):
        response = client.post("/api/v1/auth/usuarios", json={
            "nombre": "Nuevo Cajero",
            "email": "cajero@test.com",
            "password": "password123",
            "rol": "cajero",
        }, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "cajero@test.com"
        assert data["rol"] == "cajero"

    def test_registro_cerrado(self, client):
        """El endpoint /registro fue removido por seguridad."""
        response = client.post("/api/v1/auth/registro", json={
            "nombre": "Test",
            "email": "test@test.com",
            "password": "password123",
        })
        assert response.status_code in (404, 405)


class TestInventario:
    def test_crear_categoria(self, client, auth_headers):
        response = client.post("/api/v1/inventario/categorias", json={
            "nombre": "Pan de Prueba",
            "tipo": "pan_dulce",
        }, headers=auth_headers)
        assert response.status_code == 201

    def test_crear_producto(self, client, auth_headers):
        client.post("/api/v1/inventario/categorias", json={
            "nombre": "Test Cat",
            "tipo": "pan_blanco",
        }, headers=auth_headers)

        response = client.post("/api/v1/inventario/productos", json={
            "codigo": "TEST-001",
            "nombre": "Producto Test",
            "precio_unitario": "10.00",
            "tasa_iva": "0.00",
        }, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["codigo"] == "TEST-001"

    def test_listar_productos_requiere_auth(self, client):
        response = client.get("/api/v1/inventario/productos")
        assert response.status_code == 401

    def test_listar_productos(self, client, auth_headers):
        response = client.get("/api/v1/inventario/productos", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestRoot:
    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "modulos" in response.json()

    def test_health(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
