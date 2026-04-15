"""Tests para el módulo de COFEPRIS."""

import pytest


class TestCofepris:
    """Tests de cumplimiento COFEPRIS."""

    def test_registrar_temperatura_valida(self, client, auth_headers):
        resp = client.post("/api/v1/cofepris/temperaturas", json={
            "area": "refrigeracion",
            "equipo": "Refrigerador principal",
            "temperatura_registrada": "3.5",
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["en_rango"] is True

    def test_registrar_temperatura_fuera_norma(self, client, auth_headers):
        resp = client.post("/api/v1/cofepris/temperaturas", json={
            "area": "refrigeracion",
            "equipo": "Refrigerador trasero",
            "temperatura_registrada": "8.5",
        }, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["en_rango"] is False

    def test_listar_temperaturas(self, client, auth_headers):
        client.post("/api/v1/cofepris/temperaturas", json={
            "area": "produccion",
            "equipo": "Horno 1",
            "temperatura_registrada": "22.0",
        }, headers=auth_headers)
        resp = client.get("/api/v1/cofepris/temperaturas", headers=auth_headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_filtrar_temperaturas_por_area(self, client, auth_headers):
        client.post("/api/v1/cofepris/temperaturas", json={
            "area": "congelacion",
            "equipo": "Congelador",
            "temperatura_registrada": "-20.0",
        }, headers=auth_headers)
        resp = client.get("/api/v1/cofepris/temperaturas?area=congelacion", headers=auth_headers)
        assert resp.status_code == 200
        for temp in resp.json():
            assert temp["area"] == "congelacion"

    def test_alertas_temperatura(self, client, auth_headers):
        resp = client.get("/api/v1/cofepris/temperaturas/alertas", headers=auth_headers)
        assert resp.status_code == 200

    def test_registrar_limpieza(self, client, auth_headers):
        resp = client.post("/api/v1/cofepris/limpieza", json={
            "area": "produccion",
            "actividad": "Limpieza profunda de mesas",
        }, headers=auth_headers)
        assert resp.status_code == 201

    def test_listar_limpieza(self, client, auth_headers):
        resp = client.get("/api/v1/cofepris/limpieza", headers=auth_headers)
        assert resp.status_code == 200
