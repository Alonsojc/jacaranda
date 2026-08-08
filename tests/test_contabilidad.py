"""Tests para el módulo de contabilidad."""

from datetime import date, timedelta
import pytest

from app.models.egreso import Egreso
from app.services.venta_service import _hoy_operacion


class TestContabilidad:
    """Tests de contabilidad y partida doble."""

    def test_seedear_catalogo(self, client, auth_headers):
        """Seedear catálogo de cuentas SAT."""
        resp = client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["cuentas_creadas"] > 0

    def test_seedear_catalogo_idempotente(self, client, auth_headers):
        """Segundo seed no crea cuentas duplicadas."""
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        assert resp.json()["cuentas_creadas"] == 0

    def test_listar_cuentas(self, client, auth_headers):
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.get("/api/v1/contabilidad/cuentas", headers=auth_headers)
        assert resp.status_code == 200
        catalogo = resp.json()
        assert len(catalogo) > 0  # Grouped by tipo
        # Flatten all cuentas
        codigos = [c["codigo"] for cuentas in catalogo.values() for c in cuentas]
        assert "1101" in codigos  # Caja
        assert "4101" in codigos  # Ventas de pan

    def test_crear_asiento_partida_doble(self, client, auth_headers):
        """Crear asiento contable con partida doble balanceada."""
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.post("/api/v1/contabilidad/asientos", json={
            "fecha": date.today().isoformat(),
            "concepto": "Venta de pan al contado",
            "tipo": "ingreso",
            "lineas": [
                {"cuenta_codigo": "1101", "debe": "150.00", "haber": "0.00"},
                {"cuenta_codigo": "4101", "debe": "0.00", "haber": "150.00"},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["concepto"] == "Venta de pan al contado"
        assert data["numero"].startswith("I-")

    def test_asiento_desbalanceado_falla(self, client, auth_headers):
        """Partida doble: debe != haber debe fallar."""
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.post("/api/v1/contabilidad/asientos", json={
            "fecha": date.today().isoformat(),
            "concepto": "Asiento desbalanceado",
            "tipo": "diario",
            "lineas": [
                {"cuenta_codigo": "1101", "debe": "100.00", "haber": "0.00"},
                {"cuenta_codigo": "4101", "debe": "0.00", "haber": "50.00"},
            ],
        }, headers=auth_headers)
        assert resp.status_code == 400
        assert "descuadrado" in resp.json()["detail"].lower()

    def test_balance_general(self, client, auth_headers):
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        resp = client.get("/api/v1/contabilidad/balance-general", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "activos" in data
        assert "pasivos" in data
        assert "capital" in data

    def test_estado_resultados(self, client, auth_headers):
        client.post("/api/v1/contabilidad/cuentas/seed", headers=auth_headers)
        hoy = date.today()
        inicio = date(hoy.year, hoy.month, 1).isoformat()
        resp = client.get(
            f"/api/v1/contabilidad/estado-resultados?fecha_inicio={inicio}&fecha_fin={hoy.isoformat()}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "ingresos_brutos" in data
        assert "utilidad_neta" in data
        assert "isr_estimado" not in data

    def test_estado_resultados_solo_descontar_egresos_capturados(
        self, client, auth_headers, db
    ):
        hoy = date.today()
        db.add(Egreso(
            concepto="Pago de impuesto capturado",
            monto="72.00",
            categoria="impuestos",
            metodo_pago="transferencia",
            fecha=hoy,
            proveedor="SAT",
            activo=True,
        ))
        db.commit()

        resp = client.get(
            "/api/v1/contabilidad/estado-resultados"
            f"?fecha_inicio={hoy.isoformat()}&fecha_fin={hoy.isoformat()}",
            headers=auth_headers,
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_gastos_operacion"] == 72.0
        assert data["gastos_operacion"]["Pago de impuesto capturado"] == 72.0
        assert data["utilidad_neta"] == -72.0
        assert data["utilidad_neta"] == data["utilidad_operacion"]
        assert "isr_estimado" not in data

    def test_estado_resultados_incluye_mermas_capturadas(
        self, client, auth_headers
    ):
        hoy = _hoy_operacion()
        producto = client.post(
            "/api/v1/inventario/productos",
            json={
                "codigo": "MERMA-ER-001",
                "nombre": "Producto con merma contable",
                "precio_unitario": "50.00",
                "costo_produccion": "12.50",
            },
            headers=auth_headers,
        )
        assert producto.status_code == 201, producto.text
        producto_id = producto.json()["id"]
        stock = client.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo": "entrada_ajuste",
                "producto_id": producto_id,
                "cantidad": "5",
            },
            headers=auth_headers,
        )
        assert stock.status_code == 201, stock.text

        rapida = client.post(
            f"/api/v1/inventario/productos/{producto_id}/merma"
            "?cantidad=2&motivo=Producto dañado",
            headers=auth_headers,
        )
        assert rapida.status_code == 200, rapida.text
        caducidad = client.post(
            "/api/v1/merma/",
            json={
                "producto_id": producto_id,
                "tipo": "caducidad",
                "cantidad": "1",
                "fecha_merma": hoy.isoformat(),
            },
            headers=auth_headers,
        )
        assert caducidad.status_code == 201, caducidad.text

        resp = client.get(
            "/api/v1/contabilidad/estado-resultados"
            f"?fecha_inicio={hoy.isoformat()}&fecha_fin={hoy.isoformat()}",
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["mermas"] == 37.5
        assert data["utilidad_operacion"] == -37.5
        assert data["utilidad_neta"] == -37.5

    def test_estado_resultados_usa_fecha_declarada_de_merma(
        self, client, auth_headers
    ):
        fecha_merma = _hoy_operacion() - timedelta(days=7)
        producto = client.post(
            "/api/v1/inventario/productos",
            json={
                "codigo": "MERMA-FECHA-001",
                "nombre": "Producto con merma histórica",
                "precio_unitario": "40.00",
                "costo_produccion": "10.07",
            },
            headers=auth_headers,
        )
        assert producto.status_code == 201, producto.text
        producto_id = producto.json()["id"]
        stock = client.post(
            "/api/v1/inventario/movimientos",
            json={
                "tipo": "entrada_ajuste",
                "producto_id": producto_id,
                "cantidad": "2",
            },
            headers=auth_headers,
        )
        assert stock.status_code == 201, stock.text
        merma = client.post(
            "/api/v1/merma/",
            json={
                "producto_id": producto_id,
                "tipo": "dano",
                "cantidad": "1",
                "fecha_merma": fecha_merma.isoformat(),
            },
            headers=auth_headers,
        )
        assert merma.status_code == 201, merma.text

        historico = client.get(
            "/api/v1/contabilidad/estado-resultados"
            f"?fecha_inicio={fecha_merma.isoformat()}&fecha_fin={fecha_merma.isoformat()}",
            headers=auth_headers,
        )
        assert historico.status_code == 200, historico.text
        assert historico.json()["mermas"] == 10.07

        hoy = _hoy_operacion()
        actual = client.get(
            "/api/v1/contabilidad/estado-resultados"
            f"?fecha_inicio={hoy.isoformat()}&fecha_fin={hoy.isoformat()}",
            headers=auth_headers,
        )
        assert actual.status_code == 200, actual.text
        assert actual.json()["mermas"] == 0.0
