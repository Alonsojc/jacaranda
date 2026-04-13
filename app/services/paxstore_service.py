"""
Integración con PAXSTORE Cloud API para terminal PAX A910S (BBVA).
Documentación: https://github.com/PAXSTORE/paxstore-openapi-java-sdk

Permite desde el sistema Jacaranda:
- Monitorear la terminal remotamente (estado, última conexión, IP)
- Ver apps instaladas y firmware
- Enviar comandos a la terminal (reiniciar, bloquear)
- Instalar/actualizar apps en la terminal
- Consultar historial de push de apps

Requisitos:
1. Tener cuenta en PAXSTORE (admin console)
2. Habilitar "External System" en General Setting
3. Copiar el Access Key y Access Secret
4. Tu terminal debe estar registrada en PAXSTORE

Tu terminal:
- Modelo: PAX A910S
- S/N: 2841093742
- PN: A910S-0AW-RD6-25EA
"""

import json
import hmac
import hashlib
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

from app.core.config import settings


class PAXStoreError(Exception):
    pass


# ─── Autenticación ─────────────────────────────────────────────────────

def _sign_request(api_key: str, api_secret: str, timestamp: str) -> str:
    """Genera firma HMAC-SHA256 para autenticación con PAXSTORE."""
    message = f"{api_key}{timestamp}"
    signature = hmac.new(
        api_secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest().upper()
    return signature


def _paxstore_request(
    method: str, endpoint: str, data: dict | None = None
) -> dict:
    """Realiza petición autenticada al PAXSTORE Cloud API."""
    api_key = getattr(settings, "PAXSTORE_API_KEY", "")
    api_secret = getattr(settings, "PAXSTORE_API_SECRET", "")
    base_url = getattr(settings, "PAXSTORE_API_URL",
                       "https://api.whatspos.com/p-market-api")

    if not api_key or not api_secret:
        raise PAXStoreError(
            "PAXSTORE_API_KEY y PAXSTORE_API_SECRET no configurados. "
            "Ve a PAXSTORE Admin Console > General Setting > External System "
            "para obtener tus credenciales."
        )

    timestamp = str(int(time.time() * 1000))
    signature = _sign_request(api_key, api_secret, timestamp)

    url = f"{base_url}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "apiKey": api_key,
        "timestamp": timestamp,
        "signature": signature,
    }

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            if result.get("businessCode", 0) != 0:
                raise PAXStoreError(
                    f"PAXSTORE error {result.get('businessCode')}: "
                    f"{result.get('message', 'Error desconocido')}"
                )
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        raise PAXStoreError(f"PAXSTORE API error {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise PAXStoreError(f"No se pudo conectar a PAXSTORE: {e.reason}")


# ─── Terminales ────────────────────────────────────────────────────────

def buscar_terminal(serial_no: str | None = None) -> dict:
    """
    Busca terminales registradas en PAXSTORE.
    Si no se pasa serial_no, busca la terminal de Jacaranda por default.
    """
    sn = serial_no or getattr(settings, "PAX_TERMINAL_SN", "2841093742")
    result = _paxstore_request(
        "GET",
        f"/v1/3rdsys/terminals?pageNo=1&pageSize=10&snNameTID={sn}"
    )
    terminales = result.get("pageInfo", {}).get("dataSet", [])
    return terminales[0] if terminales else {}


def obtener_terminal(terminal_id: int) -> dict:
    """
    Obtiene información detallada de una terminal:
    - Estado (Activa/Inactiva/Suspendida)
    - Última conexión
    - Apps instaladas
    - Firmware
    - IP, ubicación
    """
    result = _paxstore_request(
        "GET",
        f"/v1/3rdsys/terminals/{terminal_id}"
        "?includeDetailInfoList=true"
        "&includeInstalledApks=true"
        "&includeInstalledFirmware=true"
    )
    return result.get("data", {})


def estado_terminal(serial_no: str | None = None) -> dict:
    """
    Resumen rápido del estado de la terminal PAX A910S.
    Útil para el dashboard de Jacaranda.
    """
    terminal = buscar_terminal(serial_no)
    if not terminal:
        return {"error": "Terminal no encontrada en PAXSTORE"}

    status_map = {"A": "Activa", "P": "Pendiente", "S": "Suspendida"}
    last_access = terminal.get("lastAccessTime")
    if last_access:
        last_dt = datetime.fromtimestamp(last_access / 1000, tz=timezone.utc)
        last_str = last_dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        last_str = "Desconocido"

    return {
        "nombre": terminal.get("name", ""),
        "modelo": terminal.get("modelName", "PAX A910S"),
        "serial": terminal.get("serialNo", ""),
        "tid": terminal.get("tid", ""),
        "estado": status_map.get(terminal.get("status", ""), "Desconocido"),
        "merchant": terminal.get("merchantName", ""),
        "ultima_conexion": last_str,
    }


# ─── Comandos remotos ─────────────────────────────────────────────────

def reiniciar_terminal(terminal_id: int) -> dict:
    """Envía comando de reinicio a la terminal."""
    result = _paxstore_request(
        "POST",
        f"/v1/3rdsys/terminals/{terminal_id}/commands",
        {"command": "Restart"}
    )
    return result


def bloquear_terminal(terminal_id: int) -> dict:
    """Bloquea la terminal remotamente (útil si la roban)."""
    result = _paxstore_request(
        "POST",
        f"/v1/3rdsys/terminals/{terminal_id}/commands",
        {"command": "Lock"}
    )
    return result


def desbloquear_terminal(terminal_id: int) -> dict:
    """Desbloquea la terminal."""
    result = _paxstore_request(
        "POST",
        f"/v1/3rdsys/terminals/{terminal_id}/commands",
        {"command": "Unlock"}
    )
    return result


# ─── Apps en la terminal ───────────────────────────────────────────────

def listar_apps_instaladas(serial_no: str | None = None) -> list[dict]:
    """Lista las apps instaladas en la terminal."""
    terminal = buscar_terminal(serial_no)
    if not terminal:
        return []

    terminal_id = terminal.get("id")
    detalle = obtener_terminal(terminal_id)
    apps = detalle.get("installedApks", [])

    return [
        {
            "nombre": app.get("appName", ""),
            "paquete": app.get("packageName", ""),
            "version": app.get("versionName", ""),
            "instalada": datetime.fromtimestamp(
                app["installTime"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d") if app.get("installTime") else "N/A",
        }
        for app in apps
    ]


def push_app_a_terminal(terminal_id: int, apk_id: int) -> dict:
    """
    Instala/actualiza una app en la terminal remotamente.
    El apk_id se obtiene de PAXSTORE (la app debe estar subida ahí).
    """
    result = _paxstore_request(
        "POST",
        "/v1/3rdsys/terminals/apk/push",
        {
            "terminalId": terminal_id,
            "apkId": apk_id,
        }
    )
    return result


def historial_push(terminal_id: int, limit: int = 20) -> list[dict]:
    """Consulta el historial de instalaciones remotas en la terminal."""
    result = _paxstore_request(
        "GET",
        f"/v1/3rdsys/push/history"
        f"?pageNo=1&pageSize={limit}&terminalId={terminal_id}"
    )
    return result.get("pageInfo", {}).get("dataSet", [])


# ─── Info del firmware ─────────────────────────────────────────────────

def info_firmware(serial_no: str | None = None) -> dict:
    """Obtiene información del firmware de la terminal."""
    terminal = buscar_terminal(serial_no)
    if not terminal:
        return {"error": "Terminal no encontrada"}

    detalle = obtener_terminal(terminal.get("id"))
    fw = detalle.get("installedFirmware", {})
    detail = detalle.get("terminalDetail", {})

    return {
        "firmware": fw.get("firmwareName", "N/A"),
        "os_version": detail.get("osVersion", "N/A"),
        "ip": detail.get("ip", "N/A"),
        "mac": detail.get("macAddress", "N/A"),
        "resolucion": detail.get("screenResolution", "N/A"),
        "idioma": detail.get("language", "N/A"),
    }
