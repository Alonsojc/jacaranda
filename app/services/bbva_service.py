"""
Integración con BBVA API Market para conciliación de pagos.
Documentación: https://www.bbvaapimarket.com/es/banking-apis/
Consola: https://www.bbvaapimarket.com/es/api-developers/consola-apis/

APIs disponibles:
- Business Payments: procesamiento de pagos en tiempo real
- Reconciliation: movimientos y saldos de cuenta
- Accounts: información de cuentas

Nota: La mayoría de APIs requieren registro y aprobación en BBVA API Market.
Autenticación: OAuth 2.0 (2-leg o 3-leg según el API).
"""

import json
import urllib.request
import urllib.error
from base64 import b64encode
from datetime import date
from decimal import Decimal

from app.core.config import settings


class BBVAAPIError(Exception):
    pass


def _get_access_token() -> str:
    """
    Obtiene token de acceso OAuth 2.0 (2-leg authentication).
    Requiere BBVA_CLIENT_ID y BBVA_CLIENT_SECRET del API Market.
    """
    client_id = getattr(settings, "BBVA_CLIENT_ID", "")
    client_secret = getattr(settings, "BBVA_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise BBVAAPIError(
            "BBVA_CLIENT_ID y BBVA_CLIENT_SECRET no configurados. "
            "Regístrate en https://www.bbvaapimarket.com/ para obtener credenciales."
        )

    token_url = getattr(settings, "BBVA_TOKEN_URL",
                        "https://connect.bbva.com/token")
    credentials = b64encode(f"{client_id}:{client_secret}".encode()).decode()

    data = "grant_type=client_credentials".encode()
    req = urllib.request.Request(token_url, data=data, method="POST", headers={
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return result["access_token"]
    except urllib.error.HTTPError as e:
        raise BBVAAPIError(f"Error de autenticación BBVA: {e.code}")
    except (urllib.error.URLError, KeyError) as e:
        raise BBVAAPIError(f"No se pudo autenticar con BBVA: {e}")


def _bbva_request(method: str, endpoint: str, data: dict | None = None) -> dict:
    """Realiza una petición autenticada al API de BBVA."""
    base_url = getattr(settings, "BBVA_API_URL",
                       "https://apis.bbva.com/mexico/v1")
    token = _get_access_token()
    url = f"{base_url}{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
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
        raise BBVAAPIError(f"BBVA API error {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise BBVAAPIError(f"No se pudo conectar a BBVA: {e.reason}")


# ─── Movimientos de cuenta (Reconciliation API) ────────────────────────

def obtener_movimientos(fecha_inicio: date, fecha_fin: date | None = None) -> list[dict]:
    """
    Obtiene movimientos de la cuenta BBVA para conciliación.
    Útil para comparar los cobros de la terminal TPV con los abonos en cuenta.
    """
    if not fecha_fin:
        fecha_fin = fecha_inicio
    account_id = getattr(settings, "BBVA_ACCOUNT_ID", "")
    if not account_id:
        raise BBVAAPIError("BBVA_ACCOUNT_ID no configurado")

    endpoint = (
        f"/accounts/{account_id}/transactions"
        f"?fromDate={fecha_inicio.isoformat()}"
        f"&toDate={fecha_fin.isoformat()}"
    )
    result = _bbva_request("GET", endpoint)
    return result.get("transactions", result.get("data", []))


def obtener_saldo() -> dict:
    """Consulta el saldo actual de la cuenta BBVA."""
    account_id = getattr(settings, "BBVA_ACCOUNT_ID", "")
    if not account_id:
        raise BBVAAPIError("BBVA_ACCOUNT_ID no configurado")

    result = _bbva_request("GET", f"/accounts/{account_id}/balance")
    return result


# ─── Conciliación automática ───────────────────────────────────────────

def conciliar_ventas_bbva(
    ventas_sistema: list[dict],
    fecha: date | None = None,
) -> dict:
    """
    Compara ventas del sistema marcadas como BBVA con los movimientos
    reales de la cuenta BBVA.

    Args:
        ventas_sistema: Lista de dicts con {folio, monto} de ventas BBVA
        fecha: Fecha a conciliar (default: hoy)

    Returns:
        {
            "cuadradas": [...],
            "faltantes_en_bbva": [...],
            "faltantes_en_sistema": [...],
            "total_sistema": Decimal,
            "total_bbva": Decimal,
            "diferencia": Decimal,
        }
    """
    if not fecha:
        fecha = date.today()

    try:
        movimientos = obtener_movimientos(fecha)
    except BBVAAPIError as e:
        return {
            "error": str(e),
            "ventas_sistema": ventas_sistema,
        }

    # Filtrar solo abonos de TPV (no transferencias, no domiciliaciones)
    abonos_tpv = [
        m for m in movimientos
        if m.get("type") in ("CARD_PAYMENT", "TPV", "POS")
        or "TPV" in m.get("description", "").upper()
    ]

    # Intentar emparejar por monto (BBVA no tiene referencia del POS)
    montos_bbva = [Decimal(str(m.get("amount", 0))) for m in abonos_tpv]
    montos_sistema = [Decimal(str(v["monto"])) for v in ventas_sistema]

    total_sis = sum(montos_sistema)
    total_bbva = sum(montos_bbva)

    return {
        "total_sistema": total_sis,
        "total_bbva": total_bbva,
        "diferencia": total_sis - total_bbva,
        "cuadra": total_sis == total_bbva,
        "tickets_sistema": len(ventas_sistema),
        "movimientos_bbva": len(abonos_tpv),
        "detalle_movimientos": abonos_tpv,
    }
