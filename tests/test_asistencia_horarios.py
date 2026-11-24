from datetime import datetime, timezone

from sqlalchemy import func, select

from app.core.config import settings
from app.models.asistencia import ChecadaAsistencia, PersonaHorarioAsistencia
from app.models.empleado import Empleado, RegistroAsistencia, RegistroNomina
from app.models.usuario import RolUsuario, Usuario

BASE = "/api/v1/asistencia/horarios"


def alta(client, headers, nombre, **options):
    result = client.post(BASE + "/personas", headers=headers, json={"nombre": nombre, **options})
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    return result.json()


def semana(client, headers, persona, dias, desde="2026-11-23", **options):
    return client.put(f"{BASE}/personas/{persona}/semanal", headers=headers,
                      json={"vigente_desde": desde, "dias": dias, **options})


def fecha(client, headers, persona, dia, **data):
    return client.put(f"{BASE}/personas/{persona}/fechas/{dia}", headers=headers, json=data)


def agenda(client, headers, desde="2026-11-23", hasta="2026-11-29"):
    response = client.get(BASE, headers=headers, params={"desde": desde, "hasta": hasta})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()["items"]


def test_apoyos_coberturas_y_compras_en_fecha_sin_crear_asistencia(client, auth_headers, db):
    regular = alta(client, auth_headers, "Persona de apoyo")["id"]
    purchase = alta(client, auth_headers, "Compras")["id"]
    cover = alta(client, auth_headers, "Mostrador")["id"]
    assert alta(client, auth_headers, "  PERSONA   DE APOYO ")["id"] == regular

    hours = {"entrada": "09:00", "salida": "16:00"}
    assert semana(client, auth_headers, regular, {day: hours for day in "024"}).status_code == 204
    assert semana(client, auth_headers, purchase, {day: {"entrada": "09:00", "salida": "14:00"} for day in "01234"},
                  modalidad="compras", nota="Puede iniciar fuera del local").status_code == 204
    assert fecha(client, auth_headers, regular, "2026-11-26", tipo="apoyo",
                 horas={"entrada": "10:00", "salida": "13:00"}).status_code == 204
    assert fecha(client, auth_headers, cover, "2026-11-28", tipo="cobertura",
                 horas={"entrada": "09:00", "salida": "14:00"}).status_code == 204

    rows = agenda(client, auth_headers)
    assert [r["fecha"] for r in rows if r["persona_id"] == regular] == [
        "2026-11-23", "2026-11-25", "2026-11-26", "2026-11-27",
    ]
    assert [r["tipo"] for r in rows if r["fecha"] == "2026-11-28"] == ["cobertura"]
    assert all(r["modalidad"] == "compras" and "fuera" in r["nota"]
               for r in rows if r["persona_id"] == purchase)
    assert all(r["tipo"] == "semanal" for r in agenda(client, auth_headers, "2026-11-30", "2026-12-06"))
    assert db.scalar(select(func.count()).select_from(PersonaHorarioAsistencia)) == 3
    for model in (ChecadaAsistencia, Empleado, RegistroAsistencia, RegistroNomina):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_vigencias_y_restauracion_conservan_horario_anterior(client, auth_headers):
    persona = alta(client, auth_headers, "Operación fin de semana")["id"]
    weekend = {"5": {"entrada": "10:30", "salida": "18:00"}, "6": {"entrada": "10:00", "salida": "15:00"}}
    assert semana(client, auth_headers, persona, weekend).status_code == 204
    assert semana(client, auth_headers, persona, {}, desde="2026-11-29").status_code == 204
    assert fecha(client, auth_headers, persona, "2026-11-28", tipo="descanso").status_code == 204
    rows = agenda(client, auth_headers)
    assert [(r["fecha"], r["tipo"], r["horas"]) for r in rows] == [("2026-11-28", "descanso", None)]
    path = f"{BASE}/personas/{persona}/fechas/2026-11-28"
    for _ in range(2):
        assert client.delete(path, headers=auth_headers).status_code == 204
    assert agenda(client, auth_headers)[0]["horas"] == weekend["5"]
    assert agenda(client, auth_headers, "2026-11-30", "2026-12-06") == []


def test_validacion_rechaza_turnos_invalidos(client, auth_headers):
    persona = alta(client, auth_headers, "Persona")["id"]
    for dias in ({"7": {"entrada": "09:00", "salida": "10:00"}},
                 {"0": {"entrada": "20:00", "salida": "10:00"}},
                 {"0": {"entrada": "24:00", "salida": "10:00"}}):
        assert semana(client, auth_headers, persona, dias).status_code == 422
    assert fecha(client, auth_headers, persona, "2026-11-26", tipo="apoyo").status_code == 422
    assert fecha(client, auth_headers, 9999, "2026-11-26", tipo="descanso").status_code == 404
    assert agenda(client, auth_headers) == []


def test_solo_lectura_no_puede_programar(client, auth_headers, db, admin_user):
    persona = alta(client, auth_headers, "Persona")["id"]
    admin_user.rol = RolUsuario.CONTADOR
    db.add(admin_user)
    db.commit()
    assert db.get(Usuario, admin_user.id).rol == RolUsuario.CONTADOR
    assert agenda(client, auth_headers) == []
    assert client.post(BASE + "/personas", headers=auth_headers, json={"nombre": "Otra"}).status_code == 403
    assert semana(client, auth_headers, persona, {}).status_code == 403
    assert fecha(client, auth_headers, persona, "2026-11-26", tipo="descanso").status_code == 403


def test_volumen_programado_y_registrado_incluye_checadas_en_dias_sin_turno(client, auth_headers, db, monkeypatch):
    monkeypatch.setattr(settings, "CROSSCHEX_REGION", "us")
    monkeypatch.setattr(settings, "CROSSCHEX_COMPANY_ID", "fixture")
    monkeypatch.setattr(settings, "APP_TIMEZONE", "America/Mexico_City")
    persona = alta(client, auth_headers, "Persona de apoyo", numero_reloj="009")["id"]
    assert alta(client, auth_headers, "Persona de apoyo", numero_reloj="009")["id"] == persona
    duplicate = client.post(BASE + "/personas", headers=auth_headers, json={"nombre": "Otra", "numero_reloj": "009"})
    assert duplicate.status_code == 409
    assert client.put(f"{BASE}/personas/{persona}/reloj", headers=auth_headers,
                      json={"numero_reloj": "010"}).status_code == 409
    hours = {"entrada": "09:00", "salida": "16:00"}
    assert semana(client, auth_headers, persona, {day: hours for day in "024"}).status_code == 204
    entries = [
        ("25T09:00", 128), ("25T12:00", 129), ("25T13:00", 128), ("25T16:00", 129),
        ("26T10:00", 128), ("26T12:00", 129), ("27T09:00", 128),
    ]
    for index, (stamp, code) in enumerate(entries):
        db.add(ChecadaAsistencia(identidad=f"fixture-{index}", cuenta="us:fixture", numero_reloj="009",
                                nombre_reloj="Persona", fecha=datetime.fromisoformat(f"2026-11-{stamp}:00-06:00")
                                .astimezone(timezone.utc),
                                tipo_original=code, dispositivo="DEMO", dispositivo_nombre="Demo"))
    db.commit()
    response = client.get(BASE, headers=auth_headers, params={"desde": "2026-11-23", "hasta": "2026-11-29"})
    assert response.status_code == 200
    data = response.json()
    assert data["resumen"] == [{"id": persona, "nombre": "Persona de apoyo", "numero_reloj": "009",
                               "minutos_programados": 21 * 60, "segundos_registrados": 8 * 3600, "dias_por_revisar": 1}]
    dias = {item["fecha"]: item for item in data["items"]}
    assert dias["2026-11-26"]["tipo"] == "sin_turno"
    assert dias["2026-11-26"]["segundos_registrados"] == 2 * 3600
    assert dias["2026-11-27"]["revisar_marcas"] is True
    assert dias["2026-11-27"]["segundos_registrados"] is None
