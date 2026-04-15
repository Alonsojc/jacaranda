"""Tests para el módulo de auditoría y seguridad."""

from datetime import datetime, timedelta, timezone

import pytest

BASE = "/api/v1/auditoria"


def _seed_evento(db, **kwargs):
    """Crea un LogAuditoria directamente en la BD de test."""
    from app.models.auditoria import LogAuditoria

    defaults = dict(
        usuario_id=None,
        usuario_nombre="test_user",
        accion="crear",
        modulo="ventas",
        entidad=None,
        entidad_id=None,
        datos_anteriores=None,
        datos_nuevos=None,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    defaults.update(kwargs)
    ev = LogAuditoria(**defaults)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


class TestAuditoria:

    # ------------------------------------------------------------------
    # 1. Listar eventos – tabla vacía
    # ------------------------------------------------------------------
    def test_listar_eventos_vacio(self, client, auth_headers):
        resp = client.get(f"{BASE}/", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert data == []

    # ------------------------------------------------------------------
    # 2. Dashboard de auditoría
    # ------------------------------------------------------------------
    def test_dashboard_auditoria(self, client, auth_headers):
        resp = client.get(f"{BASE}/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_eventos_hoy" in data
        assert "eventos_semana" in data
        assert "usuarios_activos_hoy" in data
        assert "anomalias_recientes" in data
        assert "ultimos_eventos" in data
        # Contadores deben ser enteros no negativos
        assert isinstance(data["total_eventos_hoy"], int)
        assert data["total_eventos_hoy"] >= 0
        assert isinstance(data["eventos_semana"], int)
        assert data["eventos_semana"] >= 0
        assert isinstance(data["usuarios_activos_hoy"], int)
        assert isinstance(data["anomalias_recientes"], list)
        assert isinstance(data["ultimos_eventos"], list)

    # ------------------------------------------------------------------
    # 3. Detección de anomalías – respuesta base
    # ------------------------------------------------------------------
    def test_anomalias_base(self, client, auth_headers):
        resp = client.get(f"{BASE}/anomalias", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # El servicio retorna una lista de anomalías (vacía si no hay nada inusual)
        assert isinstance(data, list)

    # ------------------------------------------------------------------
    # 4. Reporte de actividad con fechas válidas
    # ------------------------------------------------------------------
    def test_reporte_actividad_con_fechas(self, client, auth_headers):
        hoy = datetime.now(timezone.utc)
        inicio = (hoy - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        fin = hoy.strftime("%Y-%m-%dT%H:%M:%S")
        resp = client.get(
            f"{BASE}/reporte",
            params={"fecha_inicio": inicio, "fecha_fin": fin},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_eventos" in data
        assert "fecha_inicio" in data
        assert "fecha_fin" in data
        assert "eventos_por_usuario" in data
        assert "eventos_por_modulo" in data
        assert "horas_pico" in data
        assert isinstance(data["total_eventos"], int)
        assert isinstance(data["eventos_por_usuario"], dict)
        assert isinstance(data["eventos_por_modulo"], dict)
        assert isinstance(data["horas_pico"], list)

    # ------------------------------------------------------------------
    # 5. Reporte sin fechas → 422 Unprocessable Entity
    # ------------------------------------------------------------------
    def test_reporte_sin_fechas_falla(self, client, auth_headers):
        resp = client.get(f"{BASE}/reporte", headers=auth_headers)
        assert resp.status_code == 422

    # ------------------------------------------------------------------
    # 6. Actividad de un usuario concreto (admin_user)
    # ------------------------------------------------------------------
    def test_actividad_usuario(self, client, auth_headers, admin_user):
        resp = client.get(
            f"{BASE}/actividad/{admin_user.id}", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["usuario_id"] == admin_user.id
        assert "total_acciones" in data
        assert "por_modulo" in data
        assert "por_accion" in data
        assert "linea_tiempo" in data
        assert isinstance(data["total_acciones"], int)
        assert data["total_acciones"] >= 0

    # ------------------------------------------------------------------
    # 7. Obtener evento por ID inexistente → 404
    # ------------------------------------------------------------------
    def test_evento_no_encontrado(self, client, auth_headers):
        resp = client.get(f"{BASE}/99999", headers=auth_headers)
        assert resp.status_code == 404
        assert "Evento no encontrado" in resp.json()["detail"]

    # ------------------------------------------------------------------
    # 8. Backup de base de datos → 200 ó 400
    # ------------------------------------------------------------------
    def test_backup_base_datos(self, client, auth_headers):
        resp = client.post(f"{BASE}/backup", headers=auth_headers)
        # 200 si el entorno tiene el archivo SQLite accesible; 400 si no
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            data = resp.json()
            assert "archivo" in data
            assert "tamano_mb" in data
            assert "fecha" in data
            assert data["archivo"].endswith(".db")
            assert isinstance(data["tamano_mb"], (int, float))

    # ------------------------------------------------------------------
    # 9. Sin autenticación → 401 / 403
    # ------------------------------------------------------------------
    def test_listar_eventos_sin_auth(self, client):
        resp = client.get(f"{BASE}/")
        assert resp.status_code in (401, 403)

    def test_dashboard_sin_auth(self, client):
        resp = client.get(f"{BASE}/dashboard")
        assert resp.status_code in (401, 403)

    def test_anomalias_sin_auth(self, client):
        resp = client.get(f"{BASE}/anomalias")
        assert resp.status_code in (401, 403)

    # ------------------------------------------------------------------
    # 10. Listar eventos con filtros
    # ------------------------------------------------------------------
    def test_listar_eventos_con_filtros(self, client, auth_headers, db, admin_user):
        # Insertar dos eventos de módulos distintos
        _seed_evento(db, usuario_id=admin_user.id, modulo="inventario", accion="actualizar")
        _seed_evento(db, usuario_id=admin_user.id, modulo="ventas", accion="crear")

        # Filtrar por módulo – sólo debe devolver el de inventario
        resp = client.get(
            f"{BASE}/",
            params={"modulo": "inventario"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert all(ev["modulo"] == "inventario" for ev in data)

        # Filtrar por usuario_id
        resp2 = client.get(
            f"{BASE}/",
            params={"usuario_id": admin_user.id},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert isinstance(resp2.json(), list)

        # Filtrar por accion
        resp3 = client.get(
            f"{BASE}/",
            params={"accion": "crear"},
            headers=auth_headers,
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert all(ev["accion"] == "crear" for ev in data3)

    # ------------------------------------------------------------------
    # 11. Anomalías con parámetro dias personalizado
    # ------------------------------------------------------------------
    def test_anomalias_con_parametro_dias(self, client, auth_headers):
        for dias in (1, 14, 30, 90):
            resp = client.get(
                f"{BASE}/anomalias",
                params={"dias": dias},
                headers=auth_headers,
            )
            assert resp.status_code == 200, f"Falló con dias={dias}"
            assert isinstance(resp.json(), list)

    # ------------------------------------------------------------------
    # 12. Obtener evento existente por ID
    # ------------------------------------------------------------------
    def test_obtener_evento_existente(self, client, auth_headers, db, admin_user):
        ev = _seed_evento(
            db,
            usuario_id=admin_user.id,
            usuario_nombre=admin_user.nombre,
            modulo="auth",
            accion="login",
        )
        resp = client.get(f"{BASE}/{ev.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == ev.id
        assert data["modulo"] == "auth"
        assert data["accion"] == "login"
        assert data["usuario_id"] == admin_user.id

    # ------------------------------------------------------------------
    # 13. Listar eventos con paginación (skip / limit)
    # ------------------------------------------------------------------
    def test_listar_eventos_paginacion(self, client, auth_headers, db, admin_user):
        # Crear 5 eventos
        for i in range(5):
            _seed_evento(db, usuario_id=admin_user.id, modulo="ventas", accion="consultar")

        resp_todos = client.get(
            f"{BASE}/", params={"limit": 100}, headers=auth_headers
        )
        assert resp_todos.status_code == 200
        total = len(resp_todos.json())
        assert total >= 5

        resp_limit = client.get(
            f"{BASE}/", params={"limit": 2, "skip": 0}, headers=auth_headers
        )
        assert resp_limit.status_code == 200
        assert len(resp_limit.json()) <= 2

    # ------------------------------------------------------------------
    # 14. Reporte con fecha_fin anterior a fecha_inicio → 400
    # ------------------------------------------------------------------
    def test_reporte_fecha_fin_antes_inicio(self, client, auth_headers):
        hoy = datetime.now(timezone.utc)
        inicio = hoy.strftime("%Y-%m-%dT%H:%M:%S")
        fin = (hoy - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        resp = client.get(
            f"{BASE}/reporte",
            params={"fecha_inicio": inicio, "fecha_fin": fin},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    # ------------------------------------------------------------------
    # 15. Actividad de usuario con parámetro dias personalizado
    # ------------------------------------------------------------------
    def test_actividad_usuario_con_dias(self, client, auth_headers, admin_user):
        resp = client.get(
            f"{BASE}/actividad/{admin_user.id}",
            params={"dias": 90},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["usuario_id"] == admin_user.id
        assert data["dias"] == 90
        assert "total_acciones" in data
