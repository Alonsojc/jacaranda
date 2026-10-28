import copy
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select, func

from app.core.config import settings
from app.models.asistencia import ChecadaAsistencia, SincronizacionAsistencia, VinculoAsistencia
from app.models.empleado import Empleado, RegistroAsistencia, RegistroNomina
from app.models.usuario import RolUsuario
from app.services import asistencia_service as service
from app.services import crosschex_service as cloud

DAY = date(2026, 10, 28)
BEGIN = datetime(2026, 10, 28, 6, tzinfo=timezone.utc)
END = BEGIN + timedelta(days=1) - timedelta(microseconds=1)
BASE = "/api/v1/asistencia"


def raw_record(at="2026-10-28T15:30:00+00:00", workno="001", kind=128, serial="DEMO-EP30"):
    return {"checktime": at, "checktype": kind,
            "device": {"serial_number": serial, "name": "Reloj ficticio"},
            "employee": {"workno": workno, "first_name": "Persona", "last_name": "Prueba"}}


def page(records, number=1, total=None):
    count = len(records) if total is None else total
    return {"count": count, "list": records, "page": number, "perPage": 500,
            "pageCount": (count + 499) // 500}


@pytest.fixture
def configured(monkeypatch):
    for name, value in {
        "CROSSCHEX_ENABLED": True, "CROSSCHEX_REGION": "us", "CROSSCHEX_COMPANY_ID": "test-company",
        "CROSSCHEX_DEVICE_SERIALS": "DEMO-EP30", "CROSSCHEX_API_KEY": SecretStr("test-key"),
        "CROSSCHEX_API_SECRET": SecretStr("test-secret"), "APP_TIMEZONE": "America/Mexico_City",
    }.items():
        monkeypatch.setattr(settings, name, value)
    return cloud.configuration()


def mock_cloud(monkeypatch, pages, status=200, envelope=None):
    calls = []
    original_client = httpx.Client

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["header"]["nameSpace"] == "authorize.token":
            payload = {"token": "fixture-token", "expires": "2026-10-29T00:00:00Z"}
        else:
            payload = pages[body["payload"]["page"] - 1]
        return httpx.Response(status, json=envelope if envelope is not None else {
            "code": 200, "error": {}, "data": {"payload": payload},
        })

    def client_factory(**kwargs):
        assert kwargs == {"follow_redirects": False, "trust_env": False}
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(cloud.httpx, "Client", client_factory)
    return calls


def mock_records(monkeypatch, *records):
    monkeypatch.setattr(cloud, "fetch_records", lambda *args: ([cloud.ClockRecord.model_validate(r) for r in records], 0))


def sync(client, headers, **body):
    return client.post(BASE + "/sincronizar", headers=headers,
                       json={"desde": "2026-10-28", "hasta": "2026-10-28", **body})


def get_records(client, headers, **query):
    return client.get(BASE + "/checadas", headers=headers,
                      params={"desde": "2026-10-28", "hasta": "2026-10-28", **query})


def employee(db, number="001"):
    row = Empleado(nombre="Prueba", apellido_paterno="Local", numero_empleado=number,
                   curp="DEMO-CURP-" + number, rfc="DEMO-RFC-" + number, nss="NSS-" + number,
                   fecha_nacimiento=date(1990, 1, 1), fecha_ingreso=DAY, puesto="Prueba", salario_diario=100)
    db.add(row)
    db.commit()
    return row


def test_disabled_by_default_no_network(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "CROSSCHEX_ENABLED", False)
    monkeypatch.setattr(cloud, "fetch_records", lambda *args: pytest.fail("must not call cloud"))
    assert sync(client, auth_headers).status_code == 409
    result = client.get(BASE + "/estado", headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["lista"] is False
    assert result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("name,value", [
    ("CROSSCHEX_REGION", "https://attacker.invalid"), ("CROSSCHEX_COMPANY_ID", ""),
    ("CROSSCHEX_DEVICE_SERIALS", ""), ("CROSSCHEX_API_KEY", SecretStr("")),
    ("CROSSCHEX_API_SECRET", SecretStr("")),
])
def test_requires_scoped_configuration(configured, monkeypatch, name, value):
    monkeypatch.setattr(settings, name, value)
    assert cloud.configuration()["lista"] is False


def test_protocol_pagination_and_device_allowlist(configured, monkeypatch):
    first = [raw_record((BEGIN + timedelta(minutes=i)).isoformat()) for i in range(500)]
    second = [raw_record(serial="OTHER-COMPANY")]
    calls = mock_cloud(monkeypatch, [page(first, total=501), page(second, number=2, total=501)])
    records, omitted = cloud.fetch_records(BEGIN, END, configured)
    assert len(records) == 500 and omitted == 1
    assert calls[0]["payload"] == {"api_key": "test-key", "api_secret": "test-secret"}
    assert calls[1]["authorize"] == {"type": "token", "token": "fixture-token"}
    assert calls[1]["header"]["nameAction"] == "getrecord"
    assert calls[2]["payload"]["page"] == 2
    assert len({c["header"]["requestId"] for c in calls}) == 3


@pytest.mark.parametrize("change", ["naive_time", "wrong_page", "truncated", "out_of_range", "too_many", "bad_code"])
def test_invalid_provider_data_aborts(configured, monkeypatch, change):
    payload = page([raw_record()])
    if change == "naive_time":
        payload["list"][0]["checktime"] = "2026-10-28T09:30:00"
    elif change == "wrong_page":
        payload["page"] = 2
    elif change == "truncated":
        payload["count"] = 2
    elif change == "out_of_range":
        payload["list"][0]["checktime"] = "2026-10-27T09:30:00Z"
    elif change == "too_many":
        payload["pageCount"] = 100
    else:
        payload["list"][0]["checktype"] = "entry"
    mock_cloud(monkeypatch, [payload])
    with pytest.raises(cloud.CrossChexError):
        cloud.fetch_records(BEGIN, END, configured)


@pytest.mark.parametrize("http_status,envelope", [
    (302, None), (401, {"secret": "test-secret"}),
    (200, {"code": 401, "error": {"message": "test-secret"}}),
    (200, {"code": 200, "data": []}),
])
def test_provider_failures_are_redacted(configured, monkeypatch, http_status, envelope):
    mock_cloud(monkeypatch, [], http_status, envelope)
    with pytest.raises(cloud.CrossChexError) as error:
        cloud.fetch_records(BEGIN, END, configured)
    assert "test-secret" not in str(error.value)


def test_empty_provider_response(configured, monkeypatch):
    mock_cloud(monkeypatch, [page([])])
    assert cloud.fetch_records(BEGIN, END, configured) == ([], 0)


def test_pagination_changes_midstream(configured, monkeypatch):
    first = [raw_record() for _ in range(500)]
    mock_cloud(monkeypatch, [page(first, total=501), page([], number=2, total=500)])
    with pytest.raises(cloud.CrossChexError):
        cloud.fetch_records(BEGIN, END, configured)


def test_dedup_timezone_raw_codes_and_no_biometrics(client, auth_headers, configured, monkeypatch, db):
    raw = raw_record()
    raw["employee"]["fingerprints"] = "must-not-persist"
    same = raw_record("2026-10-28T09:30:00-06:00")
    different_type = raw_record(kind=129)
    mock_records(monkeypatch, raw, same, different_type)
    assert sync(client, auth_headers).json() == {"nuevas": 2, "repetidas": 1, "omitidas_otro_equipo": 0}
    assert sync(client, auth_headers).json()["nuevas"] == 0
    rows = db.scalars(select(ChecadaAsistencia)).all()
    assert len(rows) == 2
    assert "must-not-persist" not in str([r.__dict__ for r in rows])
    assert db.scalar(select(func.count()).select_from(RegistroAsistencia)) == 0
    assert db.scalar(select(func.count()).select_from(RegistroNomina)) == 0
    assert db.scalar(select(func.count()).select_from(SincronizacionAsistencia)) == 2


def test_daily_local_midnight_single_mark_and_search(client, auth_headers, configured, monkeypatch):
    mock_records(monkeypatch, raw_record("2026-10-28T06:01:00Z"), raw_record("2026-10-29T05:59:00Z"),
                 raw_record("2026-10-28T15:30:00Z", workno="002"))
    assert sync(client, auth_headers).status_code == 200
    response = get_records(client, auth_headers)
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["resumen"] == {"marcas": 3, "personas": 2, "sin_vincular": 2}
    assert body["total"] == 2
    assert body["items"][0]["primera"].startswith("2026-10-28T00:01")
    assert body["items"][0]["ultima"].startswith("2026-10-28T23:59")
    assert body["items"][1]["ultima"] is None
    assert get_records(client, auth_headers, buscar="002").json()["resumen"]["marcas"] == 1
    assert get_records(client, auth_headers, buscar="%").json()["total"] == 0
    assert get_records(client, auth_headers, vista="marcas", por_pagina=1, pagina=2).json()["total"] == 3


@pytest.mark.parametrize("body", [
    {"desde": "2026-10-29", "hasta": "2026-10-28"},
    {"desde": "2026-10-01", "hasta": "2026-10-08"},
    {"desde": "9999-12-31", "hasta": "9999-12-31"},
])
def test_sync_date_limits(client, auth_headers, configured, monkeypatch, body):
    monkeypatch.setattr(cloud, "fetch_records", lambda *args: pytest.fail("invalid range"))
    assert sync(client, auth_headers, **body).status_code == 422


def test_failed_fetch_leaves_no_import(client, auth_headers, configured, monkeypatch, db):
    def fail(*args):
        raise cloud.CrossChexError("Consulta incompleta")
    monkeypatch.setattr(cloud, "fetch_records", fail)
    assert sync(client, auth_headers).status_code == 502
    assert db.scalar(select(func.count()).select_from(ChecadaAsistencia)) == 0
    assert db.scalar(select(func.count()).select_from(SincronizacionAsistencia)) == 0


def test_explicit_mapping_idempotency_conflicts_and_private_selector(client, auth_headers, configured, monkeypatch, db):
    a = employee(db)
    b = employee(db, "002")
    mock_records(monkeypatch, raw_record(), raw_record(workno="002"))
    sync(client, auth_headers)
    body = {"numero_reloj": "001", "empleado_id": a.id, "motivo": "Alta del reloj"}
    assert client.post(BASE + "/vinculos", headers=auth_headers, json=body).status_code == 200
    assert client.post(BASE + "/vinculos", headers=auth_headers, json=body).status_code == 200
    assert client.post(BASE + "/vinculos", headers=auth_headers, json={**body, "empleado_id": b.id}).status_code == 409
    assert client.post(BASE + "/vinculos", headers=auth_headers, json={**body, "numero_reloj": "002"}).status_code == 409
    assert db.scalar(select(func.count()).select_from(VinculoAsistencia)) == 1
    assert get_records(client, auth_headers).json()["resumen"]["sin_vincular"] == 1
    selector = client.get(BASE + "/empleados", headers=auth_headers).json()
    assert set(selector[0]) == {"id", "nombre", "numero_empleado"}
    assert "salario" not in json.dumps(selector) and "CURP" not in json.dumps(selector)


@pytest.mark.parametrize("role", [RolUsuario.CAJERO, RolUsuario.CONSULTA, RolUsuario.PRODUCCION])
def test_unauthorized_roles_cannot_view_even_with_custom_grant(client, auth_headers, admin_user, db, role):
    admin_user.rol = role
    admin_user.permisos_modulos = {"asistencia": "editar"}
    db.commit()
    assert client.get(BASE + "/estado", headers=auth_headers).status_code == 403
    assert get_records(client, auth_headers).status_code == 403
    assert sync(client, auth_headers).status_code == 403
    assert client.get(BASE + "/empleados", headers=auth_headers).status_code == 403


def test_accountant_read_only_and_explicit_hidden(client, auth_headers, admin_user, db):
    admin_user.rol = RolUsuario.CONTADOR
    db.commit()
    assert get_records(client, auth_headers).status_code == 200
    assert sync(client, auth_headers).status_code == 403
    admin_user.permisos_modulos = {"asistencia": "oculto"}
    db.commit()
    assert get_records(client, auth_headers).status_code == 403


def test_export_formula_safety_zero_code_and_account_isolation(client, auth_headers, configured, monkeypatch):
    raw = raw_record(kind=0)
    raw["employee"]["first_name"] = "=HYPERLINK(x)"
    mock_records(monkeypatch, raw)
    sync(client, auth_headers)
    result = client.get(BASE + "/exportar", headers=auth_headers, params={"desde": str(DAY), "hasta": str(DAY)})
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    assert "'=HYPERLINK(x)" in result.text
    assert ",0,Reloj ficticio," in result.text
    monkeypatch.setattr(settings, "CROSSCHEX_COMPANY_ID", "another-company")
    assert get_records(client, auth_headers).json()["total"] == 0


def test_status_never_exposes_keys(client, auth_headers, configured):
    result = client.get(BASE + "/estado", headers=auth_headers)
    assert result.json()["lista"] is True
    assert "test-key" not in result.text and "test-secret" not in result.text


def test_history_identity_preserves_distinct_devices_and_accounts():
    raw = raw_record()
    record = cloud.ClockRecord.model_validate(raw)
    other = copy.deepcopy(raw)
    other["device"]["serial_number"] = "OTHER"
    assert cloud.record_identity("us:a", record) != cloud.record_identity("us:b", record)
    assert cloud.record_identity("us:a", record) != cloud.record_identity("us:a", cloud.ClockRecord.model_validate(other))


def test_period_boundaries_are_business_timezone(configured):
    begin, end = service.period_bounds(DAY, DAY)
    assert begin == BEGIN and end == END + timedelta(microseconds=1)


def test_import_rollback_preserves_atomicity(client, auth_headers, configured, monkeypatch, db):
    mock_records(monkeypatch, raw_record(), raw_record(workno="002"))
    def fail_audit(*args, **kwargs):
        raise RuntimeError("simulated database failure")
    monkeypatch.setattr(service, "registrar_evento", fail_audit)
    assert sync(client, auth_headers).status_code == 500
    assert db.scalar(select(func.count()).select_from(ChecadaAsistencia)) == 0
    assert db.scalar(select(func.count()).select_from(SincronizacionAsistencia)) == 0


def test_concurrent_imports_deduplicate_at_database(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.database import Base
    from app.models.usuario import Usuario

    engine = create_engine("sqlite:///" + str(tmp_path / "concurrent.sqlite"))
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Usuario(id=1, nombre="Test", email="clock@example.test", hashed_password="not-a-password"))
        db.commit()
    barrier = Barrier(2)
    record = cloud.ClockRecord.model_validate(raw_record())
    def run():
        with Session(engine) as db:
            barrier.wait()
            return service.import_records(db, [record], "us:concurrency", BEGIN, END, 0,
                                          SimpleNamespace(id=1, nombre="Test"))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        assert sorted(r["nuevas"] for r in results) == [0, 1]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(ChecadaAsistencia)) == 1
    finally:
        engine.dispose()
