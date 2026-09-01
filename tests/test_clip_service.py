import io
import json
import urllib.error
from datetime import date
from decimal import Decimal

import pytest

from app.core.config import settings
from app.services import clip_service as clip


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def configure_live_pinpad(monkeypatch):
    monkeypatch.setattr(settings, "CLIP_PINPAD_ENABLED", True)
    monkeypatch.setattr(settings, "CLIP_PINPAD_MOCK_MODE", False)
    monkeypatch.setattr(settings, "CLIP_PINPAD_AUTHORIZATION", "Bearer pinpad-test")
    monkeypatch.setattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "SN-TEST")
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://backend.test")
    monkeypatch.setattr(settings, "CLIP_WEBHOOK_SECRET", "webhook-test")
    monkeypatch.setattr(settings, "CLIP_ALLOW_UNSIGNED_WEBHOOKS", False)


def test_basic_auth_requires_both_credentials(monkeypatch):
    monkeypatch.setattr(settings, "CLIP_API_KEY", "")
    monkeypatch.setattr(settings, "CLIP_API_SECRET", "")
    with pytest.raises(clip.ClipAPIError, match="no configurados"):
        clip._get_auth_header()

    monkeypatch.setattr(settings, "CLIP_API_KEY", "key")
    monkeypatch.setattr(settings, "CLIP_API_SECRET", "secret")
    assert clip._get_auth_header() == "Basic a2V5OnNlY3JldA=="


def test_clip_request_success_and_errors(monkeypatch):
    monkeypatch.setattr(settings, "CLIP_API_KEY", "key")
    monkeypatch.setattr(settings, "CLIP_API_SECRET", "secret")
    monkeypatch.setattr(settings, "CLIP_API_URL", "https://clip.test")
    captured = {}

    def success(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(b'{"id":"pay-1"}')

    monkeypatch.setattr(clip.urllib.request, "urlopen", success)
    assert clip._clip_request("POST", "/payments", {"amount": 20}) == {"id": "pay-1"}
    assert captured["request"].full_url == "https://clip.test/payments"
    assert json.loads(captured["request"].data) == {"amount": 20}
    assert captured["timeout"] == 30

    def http_error(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://clip.test", 422, "bad", {}, io.BytesIO(b"invalid")
        )

    monkeypatch.setattr(clip.urllib.request, "urlopen", http_error)
    with pytest.raises(clip.ClipAPIError, match="error 422: invalid"):
        clip._clip_request("GET", "/payments")

    monkeypatch.setattr(
        clip.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(clip.ClipAPIError, match="offline"):
        clip._clip_request("GET", "/payments")


def test_pinpad_is_mock_until_explicitly_enabled(monkeypatch):
    monkeypatch.setattr(settings, "CLIP_PINPAD_ENABLED", False)
    monkeypatch.setattr(settings, "CLIP_PINPAD_MOCK_MODE", False)
    monkeypatch.setattr(
        clip,
        "_pinpad_request",
        lambda *_args, **_kwargs: pytest.fail("No debe abrir la red en modo deshabilitado"),
    )
    response = clip.enviar_cobro_pinpad(Decimal("18.456"), "T 1/2")
    assert response == {
        "mock": True,
        "pinpad_request_id": "mock-pinpad-T-1-2",
        "status": "pending",
        "estado": "pendiente",
        "reference": "T 1/2",
        "amount": "18.46",
        "serial_number_pos": "MOCK",
    }
    with pytest.raises(clip.ClipAPIError, match="deshabilitado"):
        clip.consultar_pago_pinpad("real-payment-id")
    with pytest.raises(clip.ClipAPIError, match="deshabilitado"):
        clip.cancelar_pago_pinpad("real-payment-id")
    with pytest.raises(clip.ClipAPIError, match="deshabilitado"):
        clip.verificar_webhook_secret_clip("secret")


def test_live_pinpad_fails_closed_when_incomplete(monkeypatch):
    monkeypatch.setattr(settings, "CLIP_PINPAD_ENABLED", True)
    monkeypatch.setattr(settings, "CLIP_PINPAD_MOCK_MODE", False)
    monkeypatch.setattr(settings, "CLIP_PINPAD_AUTHORIZATION", "")
    monkeypatch.setattr(settings, "CLIP_API_KEY", "")
    monkeypatch.setattr(settings, "CLIP_API_SECRET", "")
    monkeypatch.setattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "")
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "")
    monkeypatch.setattr(settings, "CLIP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(settings, "CLIP_ALLOW_UNSIGNED_WEBHOOKS", True)

    with pytest.raises(clip.ClipAPIError) as exc:
        clip.enviar_cobro_pinpad(Decimal("20"), "T-1")
    message = str(exc.value)
    assert "credenciales y serial" in message
    assert "BACKEND_PUBLIC_URL" in message
    assert "CLIP_WEBHOOK_SECRET" in message
    assert "CLIP_ALLOW_UNSIGNED_WEBHOOKS=false" in message


def test_live_pinpad_builds_payment_with_required_webhook(monkeypatch):
    configure_live_pinpad(monkeypatch)
    captured = {}

    def fake_request(method, endpoint, data=None, extra_headers=None):
        captured.update(
            method=method,
            endpoint=endpoint,
            data=data,
            extra_headers=extra_headers,
        )
        return {"pinpad_request_id": "pay-1", "status": "pending"}

    monkeypatch.setattr(clip, "_pinpad_request", fake_request)
    response = clip.enviar_cobro_pinpad(
        Decimal("20.005"),
        "T-1",
        descripcion="Venta T-1",
    )
    assert response["pinpad_request_id"] == "pay-1"
    assert captured["method"] == "POST"
    assert captured["endpoint"] == "/f2f/pinpad/v1/payment"
    assert captured["data"] == {
        "amount": 20.0,
        "reference": "T-1",
        "serial_number_pos": "SN-TEST",
        "webhook_url": "https://backend.test/api/v1/pagos/clip/webhook",
        "description": "Venta T-1",
    }


def test_pinpad_request_and_transport_errors(monkeypatch):
    configure_live_pinpad(monkeypatch)
    monkeypatch.setattr(settings, "CLIP_PINPAD_API_URL", "https://pinpad.test/")
    captured = {}

    def success(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse(b"")

    monkeypatch.setattr(clip.urllib.request, "urlopen", success)
    assert clip._pinpad_request("GET", "/status", extra_headers={"X-Test": "1"}) == {}
    assert captured["request"].full_url == "https://pinpad.test/status"
    assert captured["request"].get_header("Authorization") == "Bearer pinpad-test"
    assert captured["request"].get_header("X-test") == "1"

    def http_error(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://pinpad.test", 500, "bad", {}, io.BytesIO(b"down")
        )

    monkeypatch.setattr(clip.urllib.request, "urlopen", http_error)
    with pytest.raises(clip.ClipAPIError, match="PinPad API error 500"):
        clip._pinpad_request("GET", "/status")

    monkeypatch.setattr(
        clip.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(clip.ClipAPIError, match="CLIP PinPad: offline"):
        clip._pinpad_request("GET", "/status")


def test_webhook_url_and_secret_are_fail_closed(monkeypatch):
    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "")
    assert clip.clip_webhook_url(required=False) is None
    with pytest.raises(clip.ClipAPIError, match="BACKEND_PUBLIC_URL"):
        clip.clip_webhook_url()

    monkeypatch.setattr(settings, "BACKEND_PUBLIC_URL", "https://backend.test/")
    assert clip.clip_webhook_url() == "https://backend.test/api/v1/pagos/clip/webhook"

    configure_live_pinpad(monkeypatch)
    monkeypatch.setattr(settings, "CLIP_WEBHOOK_SECRET", "")
    monkeypatch.setattr(settings, "CLIP_ALLOW_UNSIGNED_WEBHOOKS", False)
    with pytest.raises(clip.ClipAPIError, match="sin secreto"):
        clip.verificar_webhook_secret_clip(None)
    monkeypatch.setattr(settings, "CLIP_ALLOW_UNSIGNED_WEBHOOKS", True)
    with pytest.raises(clip.ClipAPIError, match="debe permanecer en false"):
        clip.verificar_webhook_secret_clip(None)

    monkeypatch.setattr(settings, "CLIP_WEBHOOK_SECRET", "expected")
    monkeypatch.setattr(settings, "CLIP_ALLOW_UNSIGNED_WEBHOOKS", False)
    with pytest.raises(clip.ClipAPIError, match="no autorizado"):
        clip.verificar_webhook_secret_clip("wrong")
    clip.verificar_webhook_secret_clip("expected")


def test_consult_and_cancel_pinpad(monkeypatch):
    with pytest.raises(clip.ClipAPIError, match="Falta pinpad_request_id"):
        clip.consultar_pago_pinpad("")
    assert clip.consultar_pago_pinpad("mock-pinpad-T-1")["status"] == "pending"
    assert clip.cancelar_pago_pinpad("mock-pinpad-T-1")["status"] == "cancelled"
    with pytest.raises(clip.ClipAPIError, match="Falta pinpad_request_id"):
        clip.cancelar_pago_pinpad("")

    configure_live_pinpad(monkeypatch)
    calls = []
    monkeypatch.setattr(
        clip,
        "_pinpad_request",
        lambda method, endpoint, data=None, extra_headers=None: calls.append(
            (method, endpoint, data, extra_headers)
        ) or {"status": "pending"},
    )
    clip.consultar_pago_pinpad("pay / 1", include_detail=True)
    clip.cancelar_pago_pinpad("pay / 1")
    assert "pinpadRequestId=pay+%2F+1" in calls[0][1]
    assert calls[0][3] == {"Pinpad-Include-Detail": "true"}
    assert calls[1][1].endswith("pay%20%2F%201")


def test_request_serial_override_does_not_block_follow_up(monkeypatch):
    configure_live_pinpad(monkeypatch)
    monkeypatch.setattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "")
    calls = []
    monkeypatch.setattr(
        clip,
        "_pinpad_request",
        lambda method, endpoint, data=None, extra_headers=None: calls.append(
            (method, endpoint, data, extra_headers)
        ) or {"pinpad_request_id": "pay-override", "status": "pending"},
    )

    created = clip.enviar_cobro_pinpad(
        Decimal("20.00"),
        "T-OVERRIDE",
        serial_number_pos="SN-OVERRIDE",
    )
    assert created["pinpad_request_id"] == "pay-override"
    assert calls[0][2]["serial_number_pos"] == "SN-OVERRIDE"

    clip.consultar_pago_pinpad("pay-override")
    clip.cancelar_pago_pinpad("pay-override")
    clip.verificar_webhook_secret_clip("webhook-test")
    assert [call[0] for call in calls] == ["POST", "GET", "DELETE"]


def test_extract_status_and_confirmation_validation():
    info = clip.extraer_pago_webhook_clip({
        "id": "evt-1",
        "type": "payment.approved",
        "data": {
            "pinpadRequestId": "pay-1",
            "paymentStatus": "APPROVED",
            "externalReference": "T-1",
            "paidAmount": "20.00",
        },
    })
    assert info == {
        "event_id": "evt-1",
        "event_type": "payment.approved",
        "payment_id": "pay-1",
        "status": "approved",
        "reference": "T-1",
        "amount": "20.00",
    }
    assert clip.es_pago_clip_aprobado("CAPTURED") is True
    assert clip.es_pago_clip_fallido("declined") is True
    assert clip.estado_operativo_clip("processing") == "pendiente"
    clip.validar_confirmacion_pinpad(info, Decimal("20.00"), "pay-1")

    for changed, message in [
        ({**info, "payment_id": None}, "identificador"),
        ({**info, "payment_id": "other"}, "identificador"),
        ({**info, "amount": None}, "monto confirmado"),
        ({**info, "amount": "invalid"}, "monto inválido"),
        ({**info, "amount": "NaN"}, "monto inválido"),
        ({**info, "amount": "19.99"}, "no coincide"),
        ({**info, "amount": "0"}, "no coincide"),
    ]:
        with pytest.raises(clip.ClipAPIError, match=message):
            clip.validar_confirmacion_pinpad(changed, Decimal("20.00"), "pay-1")


def test_legacy_clip_operations_and_reconciliation(monkeypatch):
    calls = []

    def fake_request(method, endpoint, data=None):
        calls.append((method, endpoint, data))
        if endpoint.startswith("/transactions"):
            return {"data": [
                {"reference": "T-1", "amount": "20"},
                {"reference": "T-3", "amount": "5"},
            ]}
        if endpoint.startswith("/deposits"):
            return {"data": [{"id": "dep-1"}]}
        return {"id": "ok"}

    monkeypatch.setattr(clip, "_clip_request", fake_request)
    clip.enviar_cobro(Decimal("20"), "T-1", "Venta")
    clip.consultar_cobro("pay-1")
    assert clip.consultar_depositos(date(2026, 8, 1)) == [{"id": "dep-1"}]
    result = clip.conciliar_ventas_clip([
        {"folio": "T-1", "monto": "20"},
        {"folio": "T-2", "monto": "7"},
    ], date(2026, 8, 1))
    assert result["cuadradas"] == [{"folio": "T-1", "monto": "20"}]
    assert result["faltantes_en_clip"] == [{"folio": "T-2", "monto": "7"}]
    assert result["faltantes_en_sistema"] == [{"reference": "T-3", "amount": "5"}]
    assert result["diferencia"] == Decimal("2")

    monkeypatch.setattr(
        clip,
        "listar_transacciones",
        lambda _fecha=None: (_ for _ in ()).throw(clip.ClipAPIError("offline")),
    )
    assert "error" in clip.conciliar_ventas_clip([], date(2026, 8, 1))
