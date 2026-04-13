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
