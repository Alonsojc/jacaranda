"""OCR regressions use synthetic documents and never call an external provider."""

import asyncio
import base64
from datetime import date
from io import BytesIO
import json
import threading
import time
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
import httpx
from PIL import Image, ImageDraw
from pypdf import PdfWriter
import pytest

from app.core import ocr_upload
from app.services import ocr_service as ocr


def imagen(size=(700, 1000), formato="PNG", orientacion=None):
    photo = Image.new("RGB", size, "white")
    ImageDraw.Draw(photo).text((20, 20), "PROVEEDOR PRUEBA\nTOTAL MXN 125.50", fill="black")
    out = BytesIO()
    kwargs = {}
    if orientacion:
        exif = Image.Exif()
        exif[274] = orientacion
        kwargs["exif"] = exif
    photo.save(out, format=formato, **kwargs)
    return out.getvalue()


def ticket(**extra):
    return {
        "error": "", "lectura_completa": True, "proveedor": "Proveedor prueba", "fecha": date.today().isoformat(),
        "folio": "PRUEBA-1", "moneda": "MXN", "metodo_pago": "transferencia",
        "items": [{"nombre": "Bolsas kraft", "cantidad": 2, "unidad": "pz", "precio_unitario": 62.75, "total": 125.5}],
        "subtotal": 125.5, "iva": 0, "ieps": 0, "descuento": 0, "total": 125.5, "advertencias": [], **extra,
    }


def respuesta(data=None, reason="end_turn", text=None, status=200):
    content = text if text is not None else json.dumps(data if data is not None else ticket())
    return httpx.Response(status, json={"stop_reason": reason, "content": [{"type": "text", "text": content}]},
                          request=httpx.Request("POST", ocr.CLAUDE_API_URL))


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr(ocr.settings, "ANTHROPIC_API_KEY", "ocr-dummy-no-real-key")
    monkeypatch.setattr(ocr.settings, "OCR_MODEL", ocr.CLAUDE_MODEL)

    def prohibido(*args, **kwargs):
        pytest.fail("El test intento contactar un proveedor real")

    monkeypatch.setattr(ocr.httpx, "post", prohibido)


def test_extraccion_estructurada_con_mismo_modelo_y_sin_exif(monkeypatch):
    requests = []

    def post(*args, **kwargs):
        requests.append(kwargs)
        return respuesta()

    monkeypatch.setattr(ocr.httpx, "post", post)
    result = ocr.extraer_datos_ticket(imagen(formato="JPEG", orientacion=6), "image/jpeg")
    assert result["total"] == 125.5
    assert result["advertencias"] == []
    assert result["cuadre"] == "coincide"
    assert result["requiere_revision"] is True
    assert len(result["documento_id"]) == 64
    payload = requests[0]["json"]
    assert payload["model"] == ocr.CLAUDE_MODEL
    assert payload["max_tokens"] == 8192
    assert payload["output_config"]["format"]["schema"] == ocr.OCR_SCHEMA
    assert "NO CONFIABLE" in payload["system"]
    assert "anthropic-beta" not in requests[0]["headers"]
    block = payload["messages"][0]["content"][0]
    image = Image.open(BytesIO(base64.b64decode(block["source"]["data"])))
    assert image.width > image.height
    assert not image.getexif()


@pytest.mark.parametrize("formato,mime", [("PNG", "image/png"), ("WEBP", "image/webp"), ("GIF", "image/gif")])
def test_prepara_formatos_y_limita_resolucion(formato, mime):
    blocks, _ = ocr.preparar_documento(imagen((2000, 2000), formato), mime)
    assert len(blocks) == 1
    image = Image.open(BytesIO(base64.b64decode(blocks[0]["source"]["data"])))
    assert max(image.size) <= 1568
    assert image.width * image.height <= 1_152_000
    assert blocks[0]["source"]["media_type"] == "image/jpeg"


def test_ticket_largo_conserva_extremos_y_no_supera_cuatro_segmentos():
    data = Image.new("RGB", (500, 5000), "white")
    data.paste("red", (0, 0, 500, 100))
    data.paste("blue", (0, 4900, 500, 5000))
    out = BytesIO()
    data.save(out, "PNG")
    blocks, avisos = ocr.preparar_documento(out.getvalue(), "image/png")
    assert len(blocks) == 4
    first = Image.open(BytesIO(base64.b64decode(blocks[0]["source"]["data"])))
    last = Image.open(BytesIO(base64.b64decode(blocks[-1]["source"]["data"])))
    assert first.getpixel((10, 10))[0] > 200
    assert last.getpixel((10, last.height - 10))[2] > 200
    assert any("largo" in msg for msg in avisos)


def pdf(paginas=1, protegido=False):
    writer = PdfWriter()
    for _ in range(paginas):
        writer.add_blank_page(width=200, height=300)
    if protegido:
        writer.encrypt("dummy-password")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_pdf_valido_y_limites():
    blocks, avisos = ocr.preparar_documento(pdf(), "application/pdf")
    assert blocks[0]["type"] == "document"
    assert avisos == []
    for data in (pdf(11), pdf(protegido=True), b"%PDF-1.7\nincompleto"):
        with pytest.raises(ValueError):
            ocr.preparar_documento(data, "application/pdf")


@pytest.mark.parametrize("data,mime", [(b"", "image/png"), (b"\x89PNG\r\n\x1a\nbad", "image/png"), (b"data", "image/heic")])
def test_archivos_invalidos_no_llegan_al_proveedor(data, mime):
    result = ocr.extraer_datos_ticket(data, mime)
    assert result["codigo"] == "archivo_invalido"


@pytest.mark.parametrize("value", [None, -1, True, "NaN", "Infinity", {}, [], "1,250.50", 10_000_001])
def test_importes_invalidos_no_sustituyen_total_por_partidas(value):
    result = ocr.validar_resultado_ocr(ticket(total=value))
    assert result["total"] is None
    assert any("Total final" in warning for warning in result["advertencias"])


def test_no_asume_cantidad_unidad_impuestos_fecha_ni_pago():
    result = ocr.validar_resultado_ocr(ticket(
        fecha="2026-02-30", moneda=None, metodo_pago="resguardo", iva=None, ieps=None,
        items=[{"nombre": "Harina 1 kg", "cantidad": None, "unidad": None, "total": 125.5}],
    ))
    assert result["fecha"] is None
    assert result["metodo_pago"] is None
    assert result["iva"] is None
    assert result["ieps"] is None
    item = result["items"][0]
    assert item["cantidad"] is None
    assert item["unidad"] is None
    assert item["precio_unitario"] is None
    assert item["advertencias"]


def test_precio_calculado_se_identifica_y_no_se_alteran_totales():
    result = ocr.validar_resultado_ocr(ticket(items=[{"nombre": "Bolsa", "cantidad": 5, "unidad": "pz", "total": 125.5}]))
    assert result["items"][0]["precio_unitario"] == 25.1
    assert result["items"][0]["campos_calculados"] == ["precio_unitario"]
    result = ocr.validar_resultado_ocr(ticket(total=300))
    assert result["total"] == 300
    assert result["cuadre"] == "diferencia"
    assert any("no coincide" in warning for warning in result["advertencias"])


def test_impuestos_y_descuento_explicitos_pueden_cuadrar():
    result = ocr.validar_resultado_ocr(ticket(subtotal=125.5, iva=20.08, descuento=5, total=140.58))
    assert result["cuadre"] == "coincide"
    assert not result["advertencias"]


@pytest.mark.parametrize("data", [[], None, "texto", {"items": "texto"}, {"items": [None]}, {"items": [{"nombre": ""}]}])
def test_esquemas_invalidos_se_rechazan(data):
    assert ocr.validar_resultado_ocr(data)["codigo"] == "respuesta_invalida"


def test_mas_de_cien_partidas_no_se_aceptan_parcialmente():
    assert ocr.validar_resultado_ocr(ticket(items=ticket()["items"] * 101))["codigo"] == "demasiadas_partidas"


def test_partidas_ilegibles_no_se_presentan_como_ticket_completo():
    assert ocr.validar_resultado_ocr(ticket(lectura_completa=False))["codigo"] == "lectura_incompleta"


@pytest.mark.parametrize("reason", ["max_tokens", "refusal", "tool_use"])
def test_lecturas_truncadas_y_rechazadas_no_se_aceptan(monkeypatch, reason):
    monkeypatch.setattr(ocr.httpx, "post", lambda *args, **kwargs: respuesta(reason=reason))
    result = ocr.extraer_datos_ticket(imagen(), "image/png")
    assert result.get("error")
    assert "items" not in result


@pytest.mark.parametrize("text", ['{"total":NaN}', '[]', '{"items": [}', 'not json'])
def test_json_invalido_no_se_filtra_como_texto_raw(monkeypatch, text):
    monkeypatch.setattr(ocr.httpx, "post", lambda *args, **kwargs: respuesta(text=text))
    result = ocr.extraer_datos_ticket(imagen(), "image/png")
    assert result.get("error")
    assert "texto_raw" not in result


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 529])
def test_errores_del_proveedor_sanitizados_y_sin_reintentos(monkeypatch, status):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": "PRIVATE_PROVIDER_DETAIL"}},
                              request=httpx.Request("POST", ocr.CLAUDE_API_URL))

    monkeypatch.setattr(ocr.httpx, "post", post)
    result = ocr.extraer_datos_ticket(imagen(), "image/png")
    assert "PRIVATE" not in json.dumps(result)
    assert len(calls) == 1
    assert result["reintentable"] is (status == 429 or status >= 500)


def test_timeout_conexion_y_slots_se_recuperan(monkeypatch):
    for exc in (httpx.ReadTimeout("dummy"), httpx.ConnectError("dummy")):
        with patch.object(ocr.httpx, "post", side_effect=exc):
            assert ocr.extraer_datos_ticket(imagen(), "image/png")["reintentable"]
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(ocr, "_OCR_SLOTS", slots)
    slots.acquire()
    assert ocr.extraer_datos_ticket(imagen(), "image/png")["codigo"] == "ocupado"
    slots.release()
    monkeypatch.setattr(ocr.httpx, "post", lambda *args, **kwargs: respuesta())
    assert ocr.extraer_datos_ticket(imagen(), "image/png")["total"] == 125.5


@pytest.mark.parametrize("endpoint", ["/api/v1/egresos/ocr-ticket", "/api/v1/inventario/ocr-ticket"])
def test_rutas_ocr_no_crean_movimientos_y_validan_contenido(client, auth_headers, db, endpoint, monkeypatch):
    from app.models.egreso import Egreso
    from app.models.inventario import MovimientoInventario, Proveedor
    monkeypatch.setattr(ocr.httpx, "post", lambda *args, **kwargs: respuesta())
    resp = client.post(endpoint, headers=auth_headers, files={"archivo": ("sin-extension", imagen(), "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    extracted = data.get("ocr", data)
    assert extracted["total"] == 125.5
    if "suggested_egreso" in data:
        assert data["suggested_egreso"]["metodo_pago"] == "transferencia"
    assert db.query(Egreso).count() == 0
    assert db.query(MovimientoInventario).count() == 0
    assert db.query(Proveedor).count() == 0
    invalid = client.post(endpoint, headers=auth_headers, files={"archivo": ("fake.png", b"not an image", "image/png")})
    assert invalid.status_code == 400
    corrupt = client.post(endpoint, headers=auth_headers, files={"archivo": ("fake.png", b"\x89PNG\r\n\x1a\nbad", "image/png")})
    assert corrupt.status_code == 200
    assert corrupt.json().get("ocr", corrupt.json())["codigo"] == "archivo_invalido"


def test_sugerencia_no_infiere_efectivo_ni_convierte_divisas():
    from app.api.routes.egresos import _sugerir_egreso_desde_ocr
    for total in (None, "NaN", "Infinity", -1):
        suggested = _sugerir_egreso_desde_ocr(ticket(total=total, metodo_pago=None))
        assert suggested["monto"] is None
        assert suggested["metodo_pago"] is None
    assert _sugerir_egreso_desde_ocr(ticket(moneda="USD"))["monto"] is None


def test_upload_se_cierra_y_no_lee_mas_del_limite(monkeypatch):
    monkeypatch.setattr(ocr_upload, "MAX_OCR_BYTES", 10)
    upload = UploadFile(BytesIO(b"x" * 100), filename="oversize.jpg")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ocr_upload.leer_archivo_ocr(upload))
    assert exc.value.status_code == 413
    assert upload.file.closed


@pytest.mark.parametrize("modulo", ["egresos", "inventario"])
def test_ocr_no_bloquea_event_loop(monkeypatch, modulo):
    from app.api.routes import egresos, inventario
    route = egresos.ocr_ticket_egreso if modulo == "egresos" else inventario.ocr_ticket

    def slow(*args):
        time.sleep(0.18)
        return ticket()

    monkeypatch.setattr(egresos, "extraer_datos_ticket", slow)
    monkeypatch.setattr(ocr, "extraer_datos_ticket", slow)

    async def run():
        tarea = asyncio.create_task(route(UploadFile(BytesIO(imagen()), filename="ticket.png"), None))
        await asyncio.sleep(0.025)
        assert not tarea.done(), "La llamada sincronica bloqueo el event loop"
        await tarea

    asyncio.run(run())
