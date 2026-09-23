"""Preparación Uber Eats: permisos, catálogo y consultas sandbox simuladas."""

from decimal import Decimal
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.dependencies import get_current_user
from app.models.inventario import Producto, FamiliaProducto
from app.models.usuario import Usuario, RolUsuario
from app.services import uber_eats_service as svc


@pytest.fixture(autouse=True)
def sandbox(monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_CLIENT_SECRET", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_STORE_ID", "test-store")
    monkeypatch.setattr(svc, "_token_cache", None)


def test_catalogo_por_presentacion_sin_publicar_ni_cambiar_stock(db):
    familia = FamiliaProducto(nombre="Pastel")
    db.add(familia)
    db.flush()
    chico = Producto(codigo="P1", nombre="Pastel", familia_id=familia.id,
                     presentacion="chico", precio_unitario=100,
                     precio_uber_eats=Decimal("125.50"), stock_actual=3)
    grande = Producto(codigo="P2", nombre="Pastel", familia_id=familia.id,
                      presentacion="grande", precio_unitario=200, stock_actual=0)
    inactivo = Producto(codigo="P3", nombre="Retirado", precio_unitario=50, activo=False)
    db.add_all([chico, grande, inactivo])
    db.commit()
    data = svc.preparar_catalogo(db)
    assert (data["con_precio"], data["sin_precio"]) == (1, 1)
    assert data["productos"][0]["precio_centavos"] == 12550
    assert data["productos"][0]["id_propuesto"] != data["productos"][1]["id_propuesto"]
    old_id = data["productos"][0]["id_propuesto"]
    chico.codigo = "RENOMBRADO"
    db.commit()
    assert svc.preparar_catalogo(db)["productos"][0]["id_propuesto"] == old_id
    assert chico.stock_actual == 3
    assert not data["mapeo_confirmado"]


def test_sin_configuracion_no_hace_red(monkeypatch):
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ENABLED", False)
    with patch.object(svc.httpx, "Client") as client:
        with pytest.raises(svc.UberEatsError, match="Falta habilitar"):
            svc.probar_conexion()
        client.assert_not_called()
    assert not svc.configuracion()["puede_probar"]
    assert "test-secret" not in str(svc.configuracion())
    assert "test-client" not in str(svc.configuracion())


def test_sandbox_consulta_tienda_y_reutiliza_token(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert str(request.url) == svc.TOKEN_URL
            assert parse_qs(request.content.decode())["scope"] == ["eats.store"]
            return httpx.Response(200, json={"access_token": "private-token", "expires_in": 3600})
        # Marketplace Get Store Details, no la ruta delivery del ejemplo generico.
        assert str(request.url) == "https://test-api.uber.com/v1/eats/stores/test-store"
        assert request.headers["Authorization"] == "Bearer private-token"
        return httpx.Response(200, json={"store_id": "test-store", "name": "Test"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # El cliente simulado permanece abierto durante ambas consultas.
    with client, patch.object(svc.httpx, "Client") as factory:
        factory.return_value.__enter__.return_value = client
        assert svc.probar_conexion()["ok"]
        assert "private-token" not in str(svc.probar_conexion())
    assert [r.method for r in calls] == ["POST", "GET", "GET"]


@pytest.mark.parametrize("response", [
    httpx.Response(403, json={"secret": "never-expose-me"}),
    httpx.Response(302, headers={"location": "https://attacker.invalid"}),
    httpx.Response(200, content="not-json"),
    httpx.Response(200, json=[]),
    httpx.Response(200, json={"access_token": "never-expose-me", "expires_in": "bad"}),
])
def test_respuestas_invalidas_no_filtran_secretos(response):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: response))
    with client, patch.object(svc.httpx, "Client") as factory:
        factory.return_value.__enter__.return_value = client
        with pytest.raises(svc.UberEatsError) as error:
            svc.probar_conexion()
    assert "never-expose-me" not in str(error.value)


def test_token_vencido_se_renueva(monkeypatch):
    monkeypatch.setattr(svc, "_token_cache", (("test-client", "test-secret"), "old-token", 0))
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(
        200, json={"access_token": "new-token", "expires_in": 3600},
    ))) as client:
        assert svc._access_token(client) == "new-token"


@pytest.mark.parametrize("status, payload", [(200, {"id": "another-store"}), (401, {})])
def test_tienda_incorrecta_o_token_revocado_no_indican_exito(monkeypatch, status, payload):
    monkeypatch.setattr(svc, "_token_cache", (("test-client", "test-secret"), "token", float("inf")))
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload)))
    with client, patch.object(svc.httpx, "Client") as factory:
        factory.return_value.__enter__.return_value = client
        with pytest.raises(svc.UberEatsError):
            svc.probar_conexion()
    if status == 401:
        assert svc._token_cache is None


def test_timeout_de_uber_es_recuperable():
    with patch.object(svc.httpx, "Client") as factory:
        factory.return_value.__enter__.return_value.post.side_effect = httpx.ReadTimeout("private-info")
        with pytest.raises(svc.UberEatsError, match="Intenta de nuevo") as error:
            svc.probar_conexion()
    assert "private-info" not in str(error.value)


def test_preparacion_y_prueba_solo_admin(client, monkeypatch):
    from main import app
    assert client.get("/api/v1/uber-eats/preparacion").status_code == 401
    assert client.post("/api/v1/uber-eats/probar-conexion").status_code == 401
    usuario = Usuario(rol=RolUsuario.CAJERO)
    app.dependency_overrides[get_current_user] = lambda: usuario
    try:
        assert client.get("/api/v1/uber-eats/preparacion").status_code == 403
        assert client.post("/api/v1/uber-eats/probar-conexion").status_code == 403
        usuario.rol = RolUsuario.ADMINISTRADOR
        response = client.get("/api/v1/uber-eats/preparacion")
        assert response.status_code == 200
        assert response.json()["conexion"]["pedidos_automaticos"] is False
        assert "test-secret" not in response.text
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ENABLED", False)
        assert client.post("/api/v1/uber-eats/probar-conexion").status_code == 409
        monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_ENABLED", True)
        with patch.object(svc, "probar_conexion", side_effect=svc.UberEatsError("Sin conexión")):
            assert client.post("/api/v1/uber-eats/probar-conexion").status_code == 502
    finally:
        app.dependency_overrides.pop(get_current_user, None)
