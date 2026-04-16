"""Tests para el middleware de auditoría automática."""

import pytest


class TestAuditMiddleware:
    def test_mutation_doesnt_crash(self, client, auth_headers):
        """POST con audit middleware activo no rompe la respuesta."""
        resp = client.post("/api/v1/inventario/categorias", json={
            "nombre": "Test Audit Cat",
        }, headers=auth_headers)
        # El middleware no debería impedir que la request se procese
        assert resp.status_code in (200, 201, 400, 404, 422)

    def test_get_not_affected(self, client, auth_headers):
        """GET con audit middleware no se afecta."""
        resp = client.get("/api/v1/inventario/productos", headers=auth_headers)
        assert resp.status_code == 200

    def test_health_bypassed(self, client):
        """Health check pasa sin problemas."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_delete_nonexistent(self, client, auth_headers):
        """DELETE de recurso inexistente no crashea por audit middleware."""
        resp = client.delete("/api/v1/inventario/productos/99999", headers=auth_headers)
        # No debería ser 500
        assert resp.status_code != 500


class TestAuditMiddlewareHelpers:
    def test_extract_module(self):
        """Extrae módulo y entidad del path."""
        from app.core.audit_middleware import _extract_module_and_entity

        modulo, entidad, eid = _extract_module_and_entity("/api/v1/inventario/productos/5")
        assert modulo == "inventario"
        assert entidad == "productos"
        assert eid == 5

    def test_extract_module_sin_id(self):
        """Extrae módulo sin ID numérico."""
        from app.core.audit_middleware import _extract_module_and_entity

        modulo, entidad, eid = _extract_module_and_entity("/api/v1/empleados/nomina/calcular")
        assert modulo == "empleados"
        assert entidad == "nomina"
        assert eid is None

    def test_extract_module_raiz(self):
        """Path corto."""
        from app.core.audit_middleware import _extract_module_and_entity

        modulo, _, _ = _extract_module_and_entity("/api/v1/auth/login")
        assert modulo == "auth"
