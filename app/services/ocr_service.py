"""
Servicio de OCR para tickets de compra.
Usa Claude Vision API para extraer datos de fotos de tickets/facturas.
"""

import base64
import json
import httpx

from app.core.config import settings

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

PROMPT_OCR = """Eres un asistente que extrae datos de tickets de compra para una panadería en México.
Analiza esta imagen de un ticket o factura y extrae los productos comprados.

Responde SOLO con JSON válido (sin markdown, sin ```json```, solo el JSON puro) en este formato:
{
  "proveedor": "nombre de la tienda/proveedor",
  "fecha": "2026-01-15",
  "items": [
    {"nombre": "Harina de trigo", "cantidad": 5.0, "unidad": "kg", "precio_unitario": 25.50, "total": 127.50}
  ],
  "subtotal": 300.00,
  "iva": 48.00,
  "total": 348.00
}

Reglas:
- "unidad" debe ser: kg, g, l, ml, o pz (pieza)
- Si no puedes leer un campo, pon null
- Si el ticket no muestra cantidad/unidad, asume pz (pieza) y cantidad 1
- Si no puedes calcular precio_unitario, divide total entre cantidad
- Extrae TODOS los productos que veas en el ticket
- Si no es un ticket de compra, responde: {"error": "No es un ticket de compra"}"""


def extraer_datos_ticket(image_bytes: bytes, content_type: str) -> dict:
    """
    Envía una imagen o PDF a Claude API y extrae datos del ticket.

    Returns:
        dict con proveedor, items[], total, o {"error": "mensaje"}
    """
    if not settings.ANTHROPIC_API_KEY:
        return {"error": "ANTHROPIC_API_KEY no configurada. Configúrala en las variables de entorno de Railway."}

    file_b64 = base64.b64encode(image_bytes).decode("utf-8")

    if content_type == "application/pdf":
        file_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": file_b64,
            },
        }
    else:
        media_type = content_type
        if media_type not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
            media_type = "image/jpeg"
        file_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": file_b64,
            },
        }

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 2048,
        "messages": [
            {
                "role": "user",
                "content": [
                    file_block,
                    {
                        "type": "text",
                        "text": PROMPT_OCR,
                    },
                ],
            }
        ],
    }

    try:
        response = httpx.post(
            CLAUDE_API_URL,
            json=payload,
            headers={
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.TimeoutException:
        return {"error": "Timeout al procesar la imagen. Intenta con una foto más pequeña."}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"error": "API key inválida. Verifica ANTHROPIC_API_KEY."}
        return {"error": f"Error del API: {e.response.status_code}"}
    except httpx.HTTPError:
        return {"error": "Error de conexión con el servicio de OCR."}

    # Parse Claude response
    data = response.json()
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block["text"]

    # Try to parse as JSON
    text = text.strip()
    # Remove potential markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    try:
        result = json.loads(text)
        return result
    except json.JSONDecodeError:
        return {"error": "No se pudo interpretar la respuesta", "texto_raw": text}
