"""
Integración con CLIP API para terminal de pagos.
Documentación: https://developer.clip.mx/

Permite:
- Enviar cobros a la terminal CLIP desde el sistema
- Consultar transacciones del día para conciliación
- Consultar depósitos para cuadre bancario
"""

import json
import urllib.request
import urllib.error
from urllib.parse import quote, urlencode
from base64 import b64encode
from datetime import date, datetime
from decimal import Decimal

from app.core.config import settings


class ClipAPIError(Exception):
    pass


def _get_auth_header() -> str:
    """Genera el header de autenticación Basic con API Key + Secret."""
    api_key = getattr(settings, "CLIP_API_KEY", "")
    api_secret = getattr(settings, "CLIP_API_SECRET", "")
    if not api_key or not api_secret:
        raise ClipAPIError(
            "CLIP_API_KEY y CLIP_API_SECRET no configurados. "
            "Obtén tus credenciales en https://developer.clip.mx/"
        )
    token = b64encode(f"{api_key}:{api_secret}".encode()).decode()
    return f"Basic {token}"


def _clip_request(method: str, endpoint: str, data: dict | None = None) -> dict:
    """Hace una petición al API de CLIP."""
    base_url = getattr(settings, "CLIP_API_URL", "https://api.clip.mx")
    url = f"{base_url}{endpoint}"

    headers = {
        "Authorization": _get_auth_header(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise ClipAPIError(f"CLIP API error {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise ClipAPIError(f"No se pudo conectar a CLIP: {e.reason}")


def _get_pinpad_auth_header() -> str:
    """Header completo para PinPad. Permite Bearer/Basic según lo entregue Clip."""
    raw = getattr(settings, "CLIP_PINPAD_AUTHORIZATION", "").strip()
    if raw:
        return raw
    return _get_auth_header()


def _pinpad_credentials_configured(serial: str | None = None) -> bool:
    raw = getattr(settings, "CLIP_PINPAD_AUTHORIZATION", "").strip()
    basic = bool(getattr(settings, "CLIP_API_KEY", "") and getattr(settings, "CLIP_API_SECRET", ""))
    terminal = bool(serial or getattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "").strip())
    return terminal and (bool(raw) or basic)


def _pinpad_mock_enabled(serial: str | None = None) -> bool:
    return bool(getattr(settings, "CLIP_PINPAD_MOCK_MODE", False)) or not _pinpad_credentials_configured(serial)


def _pinpad_request(
    method: str,
    endpoint: str,
    data: dict | None = None,
    extra_headers: dict | None = None,
) -> dict:
    """Hace una petición al API PinPad face-to-face de Clip."""
    base_url = getattr(settings, "CLIP_PINPAD_API_URL", "https://api.payclip.io").rstrip("/")
    url = f"{base_url}{endpoint}"

    headers = {
        "Authorization": _get_pinpad_auth_header(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise ClipAPIError(f"CLIP PinPad API error {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise ClipAPIError(f"No se pudo conectar a CLIP PinPad: {e.reason}")


def clip_webhook_url(required: bool = True) -> str | None:
    """URL pública que Clip usará para avisar si el cobro se aprobó."""
    base_url = getattr(settings, "BACKEND_PUBLIC_URL", "").strip().rstrip("/")
    if not base_url:
        if not required:
            return None
        raise ClipAPIError("Configura BACKEND_PUBLIC_URL para recibir webhooks de CLIP")
    return f"{base_url}/api/v1/pagos/clip/webhook"


def _mock_pinpad_response(monto: Decimal, referencia: str, serial: str | None) -> dict:
    amount = Decimal(str(monto)).quantize(Decimal("0.01"))
    safe_reference = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in referencia)
    return {
        "mock": True,
        "pinpad_request_id": f"mock-pinpad-{safe_reference}",
        "status": "pending",
        "estado": "pendiente",
        "reference": referencia,
        "amount": str(amount),
        "serial_number_pos": serial or "MOCK",
    }


def enviar_cobro_pinpad(
    monto: Decimal,
    referencia: str,
    descripcion: str = "",
    serial_number_pos: str | None = None,
    webhook_url: str | None = None,
) -> dict:
    """
    Envía un cobro a una terminal Clip PinPad asociada a la cuenta.

    La venta queda pendiente en Jacaranda hasta que el webhook de Clip confirme
    el pago aprobado.
    """
    serial = (serial_number_pos or getattr(settings, "CLIP_PINPAD_SERIAL_NUMBER", "")).strip()
    if _pinpad_mock_enabled(serial):
        return _mock_pinpad_response(monto, referencia, serial)
    if not serial:
        raise ClipAPIError("Configura CLIP_PINPAD_SERIAL_NUMBER con el serial de tu terminal")

    payload = {
        "amount": float(Decimal(str(monto)).quantize(Decimal("0.01"))),
        "reference": referencia,
        "serial_number_pos": serial,
    }
    callback_url = webhook_url or clip_webhook_url(required=False)
    if callback_url:
        payload["webhook_url"] = callback_url
    if descripcion:
        payload["description"] = descripcion
    return _pinpad_request("POST", "/f2f/pinpad/v1/payment", payload)


def consultar_pago_pinpad(pinpad_request_id: str, include_detail: bool = True) -> dict:
    """Consulta un pago PinPad por el ID que devuelve Clip al crearlo."""
    if not pinpad_request_id:
        raise ClipAPIError("Falta pinpad_request_id para consultar CLIP")
    if str(pinpad_request_id).startswith("mock-pinpad-"):
        return {
            "mock": True,
            "pinpad_request_id": pinpad_request_id,
            "status": "pending",
            "estado": "pendiente",
        }
    endpoint = "/f2f/pinpad/v1/payment?" + urlencode({"pinpadRequestId": pinpad_request_id})
    headers = {"Pinpad-Include-Detail": "true"} if include_detail else None
    return _pinpad_request("GET", endpoint, extra_headers=headers)


def cancelar_pago_pinpad(pinpad_request_id: str) -> dict:
    """Cancela un cobro activo en una terminal PinPad."""
    if not pinpad_request_id:
        raise ClipAPIError("Falta pinpad_request_id para cancelar CLIP")
    return _pinpad_request("DELETE", f"/f2f/pinpad/v1/payment/{quote(pinpad_request_id)}")


def _pick_first(data: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def extraer_pago_webhook_clip(payload: dict) -> dict:
    """Normaliza los campos más importantes de un webhook de Clip."""
    data = payload.get("data") or payload.get("payment") or payload
    if not isinstance(data, dict):
        data = {}

    payment_id = _pick_first(
        data,
        (
            "pinpad_request_id",
            "pinpadRequestId",
            "id",
            "payment_id",
            "transaction_id",
            "paymentId",
            "transactionId",
        ),
    ) or _pick_first(
        payload,
        (
            "pinpad_request_id",
            "pinpadRequestId",
            "payment_id",
            "transaction_id",
            "paymentId",
            "transactionId",
        ),
    )
    status = _pick_first(
        data,
        ("status", "payment_status", "state", "paymentStatus"),
    ) or _pick_first(payload, ("status", "payment_status", "state", "paymentStatus"))
    reference = _pick_first(
        data,
        ("reference", "external_reference", "externalReference", "merchant_reference"),
    ) or _pick_first(
        payload,
        ("reference", "external_reference", "externalReference", "merchant_reference"),
    )
    amount = _pick_first(data, ("amount", "total", "paid_amount", "paidAmount"))
    event_id = _pick_first(payload, ("id", "event_id", "eventId"))
    event_type = _pick_first(payload, ("type", "event_type", "eventType"))

    if not event_id:
        event_id = ":".join(
            str(part)
            for part in (
                payment_id or "payment",
                status or "unknown",
                reference or "",
                _pick_first(payload, ("created_at", "createdAt", "timestamp")) or "",
            )
        )

    return {
        "event_id": str(event_id),
        "event_type": str(event_type or status or "clip.webhook"),
        "payment_id": str(payment_id) if payment_id else None,
        "status": str(status or "").lower(),
        "reference": str(reference) if reference else None,
        "amount": amount,
    }


def es_pago_clip_aprobado(status: str | None) -> bool:
    value = (status or "").lower()
    return value in {
        "approved",
        "paid",
        "completed",
        "complete",
        "successful",
        "success",
        "captured",
        "aprobado",
        "pagado",
    }


def es_pago_clip_fallido(status: str | None) -> bool:
    value = (status or "").lower()
    return value in {
        "failed",
        "declined",
        "rejected",
        "cancelled",
        "canceled",
        "expired",
        "fallido",
        "rechazado",
        "cancelado",
    }


def estado_operativo_clip(status: str | None) -> str:
    if es_pago_clip_aprobado(status):
        return "pagado"
    if es_pago_clip_fallido(status):
        return "fallido"
    return "pendiente"


def enviar_cobro(monto: Decimal, referencia: str, descripcion: str = "") -> dict:
    """
    Envía un cobro a la terminal CLIP.
    La terminal mostrará el monto y esperará que el cliente pague.

    Args:
        monto: Cantidad a cobrar en MXN
        referencia: Folio de la venta (ej: "T-00048")
        descripcion: Descripción del cobro (ej: "2x Nutella, 1x Brownies")

    Returns:
        dict con payment_id y status del cobro
    """
    payload = {
        "amount": float(monto),
        "currency": "MXN",
        "reference": referencia,
        "description": descripcion or f"Venta {referencia}",
    }
    return _clip_request("POST", "/payments", payload)


def consultar_cobro(payment_id: str) -> dict:
    """Consulta el estado de un cobro específico."""
    return _clip_request("GET", f"/payments/{payment_id}")


def listar_transacciones(fecha: date | None = None, limit: int = 100) -> list[dict]:
    """
    Lista las transacciones de CLIP para conciliación.
    Útil para el corte de caja: comparar las ventas registradas
    en el sistema vs las transacciones en CLIP.
    """
    params = f"?limit={limit}"
    if fecha:
        params += f"&date={fecha.isoformat()}"
    result = _clip_request("GET", f"/transactions{params}")
    return result.get("data", [])


def consultar_depositos(fecha_inicio: date, fecha_fin: date | None = None) -> list[dict]:
    """
    Consulta los depósitos que CLIP ha hecho a la cuenta bancaria.
    Útil para saber cuándo llega el dinero de las ventas con tarjeta.
    """
    if not fecha_fin:
        fecha_fin = fecha_inicio
    params = f"?from={fecha_inicio.isoformat()}&to={fecha_fin.isoformat()}"
    result = _clip_request("GET", f"/deposits{params}")
    return result.get("data", [])


def conciliar_ventas_clip(
    ventas_sistema: list[dict], fecha: date | None = None
) -> dict:
    """
    Compara las ventas registradas en el sistema con las transacciones de CLIP.
    Devuelve las que cuadran, las faltantes en CLIP y las faltantes en el sistema.

    Args:
        ventas_sistema: Lista de dicts con {folio, monto} de ventas con terminal CLIP
        fecha: Fecha a conciliar (default: hoy)

    Returns:
        {
            "cuadradas": [...],
            "faltantes_en_clip": [...],   # Vendí en sistema pero CLIP no tiene
            "faltantes_en_sistema": [...], # CLIP tiene pero no está en sistema
            "total_sistema": Decimal,
            "total_clip": Decimal,
            "diferencia": Decimal,
        }
    """
    try:
        txns_clip = listar_transacciones(fecha)
    except ClipAPIError:
        return {
            "error": "No se pudo conectar a CLIP API",
            "ventas_sistema": ventas_sistema,
        }

    clip_refs = {t.get("reference"): t for t in txns_clip}
    sistema_refs = {v["folio"]: v for v in ventas_sistema}

    cuadradas = []
    faltantes_clip = []
    faltantes_sistema = []

    for folio, venta in sistema_refs.items():
        if folio in clip_refs:
            cuadradas.append({"folio": folio, "monto": venta["monto"]})
        else:
            faltantes_clip.append(venta)

    for ref, txn in clip_refs.items():
        if ref not in sistema_refs:
            faltantes_sistema.append(txn)

    total_sis = sum(Decimal(str(v["monto"])) for v in ventas_sistema)
    total_clip = sum(Decimal(str(t.get("amount", 0))) for t in txns_clip)

    return {
        "cuadradas": cuadradas,
        "faltantes_en_clip": faltantes_clip,
        "faltantes_en_sistema": faltantes_sistema,
        "total_sistema": total_sis,
        "total_clip": total_clip,
        "diferencia": total_sis - total_clip,
    }
