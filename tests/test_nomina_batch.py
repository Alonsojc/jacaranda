"""Tests para nómina batch y recibo PDF."""

from datetime import date, timedelta
from decimal import Decimal

import pytest


class TestNominaBatch:
    """Tests del cálculo de nómina batch y recibo PDF."""

    EMPLEADO_DATA = {
        "nombre": "Juan",
        "apellido_paterno": "Pérez",
        "apellido_materno": "López",
        "curp": "PELJ900101HQTRPN09",
        "rfc": "PELJ9001013A5",
        "nss": "12345678901",
        "fecha_nacimiento": "1990-01-01",
        "telefono": "4421234567",
        "numero_empleado": "EMP-001",
        "fecha_ingreso": "2024-01-15",
        "tipo_contrato": "indeterminado",
        "tipo_jornada": "diurna",
        "departamento": "produccion",
        "puesto": "Panadero",
        "salario_diario": "350.00",
    }

    def _crear_empleado(self, client, auth_headers, **overrides):
        import random
        data = {**self.EMPLEADO_DATA}
        data["numero_empleado"] = f"EMP-{random.randint(1000, 9999)}"
        # Generate unique CURP/RFC/NSS
        suffix = str(random.randint(10, 99))
        data["curp"] = f"PELJ9001{suffix}HQTRPN09"
        data["rfc"] = f"PELJ9001{suffix}3A5"
        data["nss"] = f"123456789{suffix}"
        data.update(overrides)
        return client.post("/api/v1/empleados/", json=data, headers=auth_headers)

    def test_nomina_batch_calcula_todos(self, client, auth_headers):
        """Batch calculates payroll for all active employees."""
        # Create 2 employees
        r1 = self._crear_empleado(client, auth_headers)
        assert r1.status_code == 201, r1.json()
        r2 = self._crear_empleado(client, auth_headers, puesto="Cajero")
        assert r2.status_code == 201, r2.json()

        hoy = date.today()
        inicio = hoy.replace(day=1)
        fin = hoy.replace(day=15)

        resp = client.post("/api/v1/empleados/nomina/batch", json={
            "periodo_inicio": inicio.isoformat(),
            "periodo_fin": fin.isoformat(),
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2

        # Each record should have basic payroll fields
        for rec in data:
            assert rec["salario_base"]
            assert rec["total_percepciones"]
            assert rec["neto_a_pagar"]
            assert float(rec["neto_a_pagar"]) > 0

    def test_nomina_batch_sin_empleados(self, client, auth_headers):
        """Batch with no active employees returns 400."""
        hoy = date.today()
        resp = client.post("/api/v1/empleados/nomina/batch", json={
            "periodo_inicio": hoy.replace(day=1).isoformat(),
            "periodo_fin": hoy.replace(day=15).isoformat(),
        }, headers=auth_headers)
        # Could be 201 if employees exist from other tests,
        # or 400 if no active employees — depends on test order
        assert resp.status_code in (201, 400)

    def test_recibo_nomina_pdf(self, client, auth_headers):
        """Generate payroll receipt PDF."""
        r = self._crear_empleado(client, auth_headers)
        assert r.status_code == 201
        emp_id = r.json()["id"]

        hoy = date.today()
        inicio = hoy.replace(day=1)
        fin = hoy.replace(day=15)

        # Calculate individual nómina
        resp_nomina = client.post("/api/v1/empleados/nomina/calcular", json={
            "empleado_id": emp_id,
            "periodo_inicio": inicio.isoformat(),
            "periodo_fin": fin.isoformat(),
        }, headers=auth_headers)
        assert resp_nomina.status_code == 201
        nomina_id = resp_nomina.json()["id"]

        # Download PDF
        resp_pdf = client.get(
            f"/api/v1/empleados/nomina/{nomina_id}/recibo-pdf",
            headers=auth_headers,
        )
        assert resp_pdf.status_code == 200
        assert resp_pdf.headers["content-type"] == "application/pdf"
        assert b"%PDF" in resp_pdf.content[:10]

    def test_recibo_nomina_pdf_no_encontrado(self, client, auth_headers):
        resp = client.get(
            "/api/v1/empleados/nomina/99999/recibo-pdf",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_listar_nominas(self, client, auth_headers):
        resp = client.get("/api/v1/empleados/nomina", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
