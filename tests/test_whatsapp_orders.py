"""Tests para creación de pedidos vía WhatsApp y notificaciones."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest


class TestWhatsAppOrders:
    """Tests del flujo de pedidos por WhatsApp."""

    def _crear_producto(self, client, auth_headers, nombre="Concha", precio="15.00"):
        import random
        codigo = f"WA-{random.randint(1000, 9999)}"
        resp = client.post("/api/v1/inventario/productos", json={
            "codigo": codigo,
            "nombre": nombre,
            "precio_unitario": precio,
            "tasa_iva": "0.16",
        }, headers=auth_headers)
        pid = resp.json()["id"]
        # Add stock
        client.post("/api/v1/inventario/movimientos", json={
            "tipo": "entrada_ajuste",
            "producto_id": pid,
            "cantidad": "50",
            "referencia": "Stock test WA",
        }, headers=auth_headers)
        return pid

    @patch("app.services.whatsapp_service._enviar_mensaje")
    def test_crear_pedido_via_whatsapp(self, mock_enviar, client, auth_headers):
        """Test creating an order via WhatsApp message."""
        self._crear_producto(client, auth_headers, "Conchas", "15.00")

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "5214421234567",
                            "type": "text",
                            "text": {"body": "pedido 3 conchas"},
                        }]
                    }
                }]
            }]
        }
        resp = client.post("/api/v1/whatsapp/webhook", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["processed"] == 1
        result = data["results"][0]
        assert result["tipo"] == "pedido_creado"
        assert result["pedido_folio"]
        assert float(result["total"]) == 45.00  # 3 * 15
        mock_enviar.assert_called()

    @patch("app.services.whatsapp_service._enviar_mensaje")
    def test_pedido_multiples_items(self, mock_enviar, client, auth_headers):
        """Test order with multiple comma-separated items."""
        self._crear_producto(client, auth_headers, "Conchas", "15.00")
        self._crear_producto(client, auth_headers, "Pastel Chocolate", "250.00")

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "5214421234567",
                            "type": "text",
                            "text": {"body": "pedido 2 conchas, 1 pastel chocolate"},
                        }]
                    }
                }]
            }]
        }
        resp = client.post("/api/v1/whatsapp/webhook", json=payload)
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["tipo"] == "pedido_creado"

    @patch("app.services.whatsapp_service._enviar_mensaje")
    def test_pedido_producto_no_encontrado(self, mock_enviar, client, auth_headers):
        """When no products match, should return error."""
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "5214421234567",
                            "type": "text",
                            "text": {"body": "pedido 2 producto_inexistente_xyz"},
                        }]
                    }
                }]
            }]
        }
        resp = client.post("/api/v1/whatsapp/webhook", json=payload)
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["tipo"] == "pedido_error"
        assert result["error"] == "productos_no_encontrados"

    @patch("app.services.whatsapp_service._enviar_mensaje")
    def test_catalogo_whatsapp(self, mock_enviar, client, auth_headers):
        """Test 'catalogo' keyword triggers catalog response."""
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "5214421234567",
                            "type": "text",
                            "text": {"body": "catálogo"},
                        }]
                    }
                }]
            }]
        }
        resp = client.post("/api/v1/whatsapp/webhook", json=payload)
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["tipo"] == "catalogo"

    @patch("app.services.whatsapp_service._enviar_mensaje")
    def test_saludo_default(self, mock_enviar, client, auth_headers):
        """Unknown text triggers greeting/help."""
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "5214421234567",
                            "type": "text",
                            "text": {"body": "hola"},
                        }]
                    }
                }]
            }]
        }
        resp = client.post("/api/v1/whatsapp/webhook", json=payload)
        assert resp.status_code == 200
        result = resp.json()["results"][0]
        assert result["tipo"] == "saludo"


class TestWhatsAppRecordatorio:
    """Tests del endpoint de recordatorio de entrega."""

    def _crear_pedido(self, client, auth_headers):
        return client.post("/api/v1/pedidos/", json={
            "cliente_nombre": "Test WA",
            "cliente_telefono": "4421234567",
            "fecha_entrega": (date.today() + timedelta(days=1)).isoformat(),
            "hora_entrega": "14:00",
            "origen": "whatsapp",
            "detalles": [
                {"descripcion": "Pan dulce", "cantidad": 6, "precio_unitario": "15.00"},
            ],
        }, headers=auth_headers)

    @patch("app.services.whatsapp_service._enviar_mensaje")
    def test_enviar_recordatorio(self, mock_enviar, client, auth_headers):
        resp = self._crear_pedido(client, auth_headers)
        pid = resp.json()["id"]

        resp2 = client.post(f"/api/v1/whatsapp/recordatorio/{pid}", headers=auth_headers)
        assert resp2.status_code == 200
        assert resp2.json()["ok"] is True

    def test_recordatorio_pedido_inexistente(self, client, auth_headers):
        resp = client.post("/api/v1/whatsapp/recordatorio/99999", headers=auth_headers)
        assert resp.status_code == 404


class TestParsearItems:
    """Unit tests for item parsing logic."""

    def test_parsear_items_basico(self):
        from app.services.whatsapp_service import _parsear_items_pedido
        items = _parsear_items_pedido("2 conchas, 1 pastel chocolate")
        assert len(items) == 2
        assert items[0] == {"cantidad": 2, "nombre": "conchas"}
        assert items[1] == {"cantidad": 1, "nombre": "pastel chocolate"}

    def test_parsear_items_sin_cantidad(self):
        from app.services.whatsapp_service import _parsear_items_pedido
        items = _parsear_items_pedido("concha")
        assert len(items) == 1
        assert items[0] == {"cantidad": 1, "nombre": "concha"}

    def test_parsear_items_vacio(self):
        from app.services.whatsapp_service import _parsear_items_pedido
        items = _parsear_items_pedido("")
        assert items == []
