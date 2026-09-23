"""Preparación de catálogo y diagnóstico de Uber Eats Marketplace en sandbox."""

from decimal import Decimal
from threading import Lock
from time import monotonic
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.inventario import Producto


TOKEN_URL = "https://sandbox-login.uber.com/oauth/v2/token"
API_URL = "https://test-api.uber.com"
_token_lock = Lock()
_token_cache = None


class UberEatsError(Exception):
    pass


def configuracion() -> dict:
    campos = {
        "client_id": bool(settings.UBER_EATS_SANDBOX_CLIENT_ID.strip()),
        "client_secret": bool(settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value()),
        "store_id": bool(settings.UBER_EATS_SANDBOX_STORE_ID.strip()),
    }
    return {
        "entorno": "sandbox",
        "habilitado": settings.UBER_EATS_SANDBOX_ENABLED,
        "credenciales": campos,
        "puede_probar": settings.UBER_EATS_SANDBOX_ENABLED and all(campos.values()),
        "pedidos_automaticos": False,
        "publicacion_menu": False,
    }


def preparar_catalogo(db: Session) -> dict:
    productos = (
        db.query(Producto)
        .options(joinedload(Producto.familia))
        .filter(Producto.activo.is_(True))
        .order_by(Producto.nombre, Producto.id)
        .all()
    )
    filas = []
    for producto in productos:
        precio = producto.precio_uber_eats
        con_precio = precio is not None and precio > 0
        filas.append({
            "producto_id": producto.id,
            # El codigo editable y el nombre no son claves de integracion.
            "id_propuesto": f"jacaranda-producto-{producto.id}",
            "codigo": producto.codigo,
            "nombre": producto.nombre,
            "familia": producto.familia.nombre if producto.familia else None,
            "presentacion": producto.presentacion,
            "precio_uber_eats": str(precio) if con_precio else None,
            "precio_centavos": int(precio * Decimal("100")) if con_precio else None,
            "con_precio": con_precio,
            "sin_stock": producto.stock_actual <= 0,
        })
    return {
        "moneda": "MXN",
        "productos": filas,
        "con_precio": sum(p["con_precio"] for p in filas),
        "sin_precio": sum(not p["con_precio"] for p in filas),
        "mapeo_confirmado": False,
    }


def _json_response(response: httpx.Response) -> dict:
    if response.status_code >= 300:
        # No propagar respuestas externas: pueden contener tokens o datos personales.
        raise UberEatsError(f"Uber rechazó la consulta (HTTP {response.status_code}). Revisa permisos y credenciales de pruebas.")
    try:
        data = response.json()
    except ValueError:
        raise UberEatsError("Uber devolvió una respuesta no válida.") from None
    if not isinstance(data, dict):
        raise UberEatsError("Uber devolvió una respuesta no válida.")
    return data


def _access_token(client: httpx.Client) -> str:
    global _token_cache
    key = (
        settings.UBER_EATS_SANDBOX_CLIENT_ID.strip(),
        settings.UBER_EATS_SANDBOX_CLIENT_SECRET.get_secret_value(),
    )
    # Reutilizar tokens evita el limite de autenticaciones de Uber.
    with _token_lock:
        if _token_cache and _token_cache[0] == key and _token_cache[2] > monotonic():
            return _token_cache[1]
        data = _json_response(client.post(TOKEN_URL, data={
            "client_id": key[0], "client_secret": key[1],
            "grant_type": "client_credentials", "scope": "eats.store",
        }))
        token = data.get("access_token")
        try:
            expires = int(data.get("expires_in", 0))
        except (TypeError, ValueError):
            expires = 0
        if not isinstance(token, str) or not token.strip() or expires <= 0:
            raise UberEatsError("Uber no devolvió un token válido.")
        _token_cache = (key, token, monotonic() + max(0, expires - 60))
        return token


def probar_conexion() -> dict:
    global _token_cache
    if not configuracion()["puede_probar"]:
        raise UberEatsError("Falta habilitar y configurar la conexión de pruebas en el servidor.")
    store_id = settings.UBER_EATS_SANDBOX_STORE_ID.strip()
    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            token = _access_token(client)
            response = client.get(
                f"{API_URL}/v1/eats/stores/{quote(store_id, safe='')}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            if response.status_code == 401:
                with _token_lock:
                    _token_cache = None
            store = _json_response(response)
    except httpx.HTTPError:
        raise UberEatsError("No se pudo consultar Uber. Intenta de nuevo más tarde.") from None
    if store.get("store_id", store.get("id")) != store_id:
        raise UberEatsError("Uber no confirmó la tienda de pruebas configurada.")
    return {"ok": True, "entorno": "sandbox", "mensaje": "Conexión de pruebas verificada. Pedidos automáticos pendientes de activación."}
