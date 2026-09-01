import hashlib
import hmac
import io
import json
import urllib.error

import pytest

from app.core.config import settings
from app.services import paxstore_service as pax


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def enable_pax(monkeypatch, *, remote=False):
    monkeypatch.setattr(settings, "PAXSTORE_ENABLED", True)
    monkeypatch.setattr(settings, "PAXSTORE_ALLOW_REMOTE_COMMANDS", remote)
    monkeypatch.setattr(settings, "PAXSTORE_API_KEY", "test-key")
    monkeypatch.setattr(settings, "PAXSTORE_API_SECRET", "test-secret")
    monkeypatch.setattr(settings, "PAXSTORE_API_URL", "https://pax.test/api/")


def test_sign_request_uses_hmac_sha256():
    expected = hmac.new(
        b"secret",
        b"key1700000000000",
        hashlib.sha256,
    ).hexdigest().upper()
    assert pax._sign_request("key", "secret", "1700000000000") == expected


def test_paxstore_disabled_never_opens_network(monkeypatch):
    monkeypatch.setattr(settings, "PAXSTORE_ENABLED", False)
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(pax.urllib.request, "urlopen", fail_if_called)
    with pytest.raises(pax.PAXStoreError, match="deshabilitado"):
        pax._paxstore_request("GET", "/terminals")
    assert called is False


def test_paxstore_requires_credentials_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "PAXSTORE_ENABLED", True)
    monkeypatch.setattr(settings, "PAXSTORE_API_KEY", "")
    monkeypatch.setattr(settings, "PAXSTORE_API_SECRET", "")
    with pytest.raises(pax.PAXStoreError, match="no configurados"):
        pax._paxstore_request("GET", "/terminals")


def test_paxstore_request_signs_and_serializes(monkeypatch):
    enable_pax(monkeypatch)
    monkeypatch.setattr(pax.time, "time", lambda: 1700000000.125)
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(json.dumps({"businessCode": "0000", "data": {"ok": True}}).encode())

    monkeypatch.setattr(pax.urllib.request, "urlopen", fake_urlopen)
    result = pax._paxstore_request("POST", "/command", {"command": "Status"})

    request = captured["request"]
    assert result["data"] == {"ok": True}
    assert request.full_url == "https://pax.test/api/command"
    assert request.method == "POST"
    assert json.loads(request.data) == {"command": "Status"}
    assert request.get_header("Apikey") == "test-key"
    assert request.get_header("Timestamp") == "1700000000125"
    assert request.get_header("Signature") == pax._sign_request(
        "test-key", "test-secret", "1700000000125"
    )
    assert captured["timeout"] == 30


def test_paxstore_rejects_business_error(monkeypatch):
    enable_pax(monkeypatch)
    monkeypatch.setattr(
        pax.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(
            b'{"businessCode": "1001", "message": "denied"}'
        ),
    )
    with pytest.raises(pax.PAXStoreError, match="1001: denied"):
        pax._paxstore_request("GET", "/terminals")


def test_paxstore_rejects_invalid_json(monkeypatch):
    enable_pax(monkeypatch)
    monkeypatch.setattr(
        pax.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(b"not-json"),
    )
    with pytest.raises(pax.PAXStoreError, match="respuesta inválida"):
        pax._paxstore_request("GET", "/terminals")


def test_paxstore_wraps_http_and_network_errors(monkeypatch):
    enable_pax(monkeypatch)

    def http_error(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://pax.test",
            403,
            "Forbidden",
            {},
            io.BytesIO(b"forbidden"),
        )

    monkeypatch.setattr(pax.urllib.request, "urlopen", http_error)
    with pytest.raises(pax.PAXStoreError, match="API error 403: forbidden"):
        pax._paxstore_request("GET", "/terminals")

    def network_error(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(pax.urllib.request, "urlopen", network_error)
    with pytest.raises(pax.PAXStoreError, match="offline"):
        pax._paxstore_request("GET", "/terminals")


def test_buscar_terminal_requires_and_encodes_serial(monkeypatch):
    monkeypatch.setattr(settings, "PAX_TERMINAL_SN", "")
    with pytest.raises(pax.PAXStoreError, match="proporciona un serial"):
        pax.buscar_terminal()

    calls = []
    monkeypatch.setattr(
        pax,
        "_paxstore_request",
        lambda method, endpoint, data=None: calls.append((method, endpoint, data))
        or {"pageInfo": {"dataSet": [{"id": 7}] }},
    )
    assert pax.buscar_terminal(" SN / 42 ") == {"id": 7}
    assert calls[0][0] == "GET"
    assert "snNameTID=SN+%2F+42" in calls[0][1]

    monkeypatch.setattr(
        pax,
        "_paxstore_request",
        lambda *_args, **_kwargs: {"pageInfo": {"dataSet": []}},
    )
    assert pax.buscar_terminal("missing") == {}


def test_terminal_detail_and_status(monkeypatch):
    calls = []
    monkeypatch.setattr(
        pax,
        "_paxstore_request",
        lambda method, endpoint, data=None: calls.append((method, endpoint, data))
        or {"data": {"id": 9}},
    )
    assert pax.obtener_terminal(9) == {"id": 9}
    assert "/terminals/9?" in calls[0][1]
    with pytest.raises(pax.PAXStoreError, match="entero positivo"):
        pax.obtener_terminal(0)
    with pytest.raises(pax.PAXStoreError, match="entero positivo"):
        pax.obtener_terminal("invalid")

    monkeypatch.setattr(
        pax,
        "buscar_terminal",
        lambda _serial=None: {
            "name": "Caja",
            "modelName": "A910S",
            "serialNo": "SN-TEST",
            "tid": "T-1",
            "status": "A",
            "merchantName": "Jacaranda",
            "lastAccessTime": 0,
        },
    )
    status = pax.estado_terminal()
    assert status["estado"] == "Activa"
    assert status["ultima_conexion"] == "Desconocido"

    monkeypatch.setattr(
        pax,
        "buscar_terminal",
        lambda _serial=None: {
            "status": "S",
            "lastAccessTime": 1700000000000,
        },
    )
    status = pax.estado_terminal()
    assert status["estado"] == "Suspendida"
    assert status["ultima_conexion"] == "2023-11-14 22:13:20"

    monkeypatch.setattr(pax, "buscar_terminal", lambda _serial=None: {})
    assert "error" in pax.estado_terminal()


@pytest.mark.parametrize(
    ("function_name", "command"),
    [
        ("reiniciar_terminal", "Restart"),
        ("bloquear_terminal", "Lock"),
        ("desbloquear_terminal", "Unlock"),
    ],
)
def test_remote_commands_need_second_gate(monkeypatch, function_name, command):
    enable_pax(monkeypatch, remote=False)
    function = getattr(pax, function_name)
    with pytest.raises(pax.PAXStoreError, match="comandos remotos"):
        function(4)

    monkeypatch.setattr(settings, "PAXSTORE_ALLOW_REMOTE_COMMANDS", True)
    calls = []
    monkeypatch.setattr(
        pax,
        "_paxstore_request",
        lambda method, endpoint, data=None: calls.append((method, endpoint, data))
        or {"ok": True},
    )
    assert function(4) == {"ok": True}
    assert calls == [("POST", "/v1/3rdsys/terminals/4/commands", {"command": command})]


def test_apps_push_history_and_firmware(monkeypatch):
    monkeypatch.setattr(pax, "buscar_terminal", lambda _serial=None: {"id": 12})
    monkeypatch.setattr(
        pax,
        "obtener_terminal",
        lambda _terminal_id: {
            "installedApks": [
                {
                    "appName": "Pago",
                    "packageName": "mx.test.pay",
                    "versionName": "1.2",
                    "installTime": 1700000000000,
                },
                {"appName": "Sin fecha"},
            ],
            "installedFirmware": {"firmwareName": "FW-1"},
            "terminalDetail": {
                "osVersion": "10",
                "ip": "10.0.0.1",
                "macAddress": "00:00",
                "screenResolution": "720x1280",
                "language": "es",
            },
        },
    )
    apps = pax.listar_apps_instaladas()
    assert apps[0]["instalada"] == "2023-11-14"
    assert apps[1]["instalada"] == "N/A"
    assert pax.info_firmware()["firmware"] == "FW-1"

    enable_pax(monkeypatch, remote=True)
    calls = []
    monkeypatch.setattr(
        pax,
        "_paxstore_request",
        lambda method, endpoint, data=None: calls.append((method, endpoint, data))
        or ({"pageInfo": {"dataSet": [{"id": 1}]}} if method == "GET" else {"ok": True}),
    )
    assert pax.push_app_a_terminal(12, 33) == {"ok": True}
    assert calls[0][2] == {"terminalId": 12, "apkId": 33}
    assert pax.historial_push(12, 500) == [{"id": 1}]
    assert "pageSize=100" in calls[1][1]
    with pytest.raises(pax.PAXStoreError, match="entero positivo"):
        pax.historial_push(12, 0)


def test_empty_terminal_has_no_apps_or_firmware(monkeypatch):
    monkeypatch.setattr(pax, "buscar_terminal", lambda _serial=None: {})
    assert pax.listar_apps_instaladas() == []
    assert pax.info_firmware() == {"error": "Terminal no encontrada"}
