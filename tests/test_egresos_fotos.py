"""Fotos de tablas con datos sinteticos; nunca se llama al OCR real."""

from datetime import date
import base64
from io import BytesIO
import json

import httpx
from PIL import Image
import pytest

from app.api.routes import egresos
from app.models.auditoria import LogAuditoria
from app.models.egreso import Egreso
from app.models.inventario import Proveedor
from app.models.usuario import RolUsuario
from app.services import egresos_photo_service as photos, ocr_service as ocr

PATH = "/api/v1/egresos/importacion/"


def photo():
    out = BytesIO()
    Image.new("RGB", (500, 800), "white").save(out, "PNG")
    return out.getvalue()


def row(**extra):
    return {"fecha": "01-sep-26", "proveedor": "Proveedor sintetico", "monto": "178.49",
            "metodo_pago": "TARJETA", "legible": True, "es_total": False, "advertencias": [], **extra}


def parsed(rows=None, **extra):
    return photos.validar_tabla_gastos({"error": "", "moneda": "MXN", "advertencias": [],
                                      "filas": rows if rows is not None else [row()], **extra})


def preview(client, headers, monkeypatch, rows=None, **extra):
    monkeypatch.setattr(egresos, "extraer_tabla_gastos", lambda *args: parsed(rows, **extra))
    response = client.post(PATH + "foto/previsualizar", headers=headers,
                           files={"archivo": ("tabla.png", photo(), "image/png")})
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, headers, view, **extra):
    return client.post(PATH + "confirmar", headers=headers, json={"token": view["token"],
        "filas": [f["fila"] for f in view["filas"] if f["estado"] == "lista"],
        "revision_confirmada": True, **extra})


def test_photo_preview_review_and_idempotent_audited_import(client, auth_headers, db, monkeypatch):
    view = preview(client, auth_headers, monkeypatch, [row(), row(fecha="02-sep-26", monto="1,000.00", metodo_pago="A CREDITO")])
    assert view["tipo"] == "foto" and view["total_listas"] == "1178.49"
    assert [f["datos"]["origen"] for f in view["filas"]] == ["ocr", "ocr"]
    assert view["filas"][1]["datos"]["metodo_pago"] == "credito"
    assert db.query(Egreso).count() == db.query(Proveedor).count() == 0
    assert confirm(client, auth_headers, view, revision_confirmada=False).status_code == 400
    done = confirm(client, auth_headers, view)
    assert done.status_code == 200, done.text
    assert done.json()["importados"] == 2
    assert db.query(Egreso).count() == 2
    audit = json.loads(db.query(LogAuditoria).filter_by(entidad="egreso").first().datos_nuevos)
    assert audit["importacion_foto"]["tipo"] == "foto"
    assert len(audit["importacion_foto"]["sha256"]) == 64
    assert "importacion_excel" not in audit
    assert confirm(client, auth_headers, view).json()["ya_registrados"] == 2
    repeated = preview(client, auth_headers, monkeypatch, [row(), row(fecha="02-sep-26", monto="1,000.00", metodo_pago="A CREDITO")])
    assert [f["estado"] for f in repeated["filas"]] == ["registrada", "registrada"]


@pytest.mark.parametrize("changes", [{"monto": "190.00"}, {"metodo_pago": "EFECTIVO"}, {}])
def test_existing_provider_date_conflict_is_not_automatically_added(client, auth_headers, db, monkeypatch, changes):
    db.add(Egreso(concepto="Compra anterior", proveedor="PROVEEDOR SINTETICO", monto="178.49",
                  fecha=date(2026, 9, 1), metodo_pago="tarjeta", categoria="operativo"))
    db.commit()
    view = preview(client, auth_headers, monkeypatch, [row(**changes)])
    assert view["filas"][0]["estado"] == "duplicado"
    assert confirm(client, auth_headers, view, filas=[1]).status_code == 409
    assert db.query(Egreso).count() == 1


def test_different_payments_with_same_date_amount_are_not_duplicated(client, auth_headers, db, monkeypatch):
    view = preview(client, auth_headers, monkeypatch, [row(), row(metodo_pago="EFECTIVO")])
    assert [f["estado"] for f in view["filas"]] == ["lista", "duplicado"]
    assert confirm(client, auth_headers, view, filas=[1, 2]).status_code == 409
    assert db.query(Egreso).count() == 0
    assert confirm(client, auth_headers, view).json()["importados"] == 1


def test_same_provider_date_distinct_visible_purchases_remain_separate(client, auth_headers, db, monkeypatch):
    view = preview(client, auth_headers, monkeypatch, [row(), row(monto="200.00", metodo_pago="EFECTIVO")])
    assert [f["estado"] for f in view["filas"]] == ["lista", "lista"]
    assert confirm(client, auth_headers, view).json()["importados"] == 2


def test_new_conflict_before_commit_rolls_back_entire_batch(client, auth_headers, db, monkeypatch):
    view = preview(client, auth_headers, monkeypatch, [row(), row(fecha="02-sep-26")])
    db.add(Egreso(concepto="Alta concurrente", proveedor="Proveedor sintetico", monto=200,
                  fecha=date(2026, 9, 2), metodo_pago="efectivo", categoria="operativo"))
    db.commit()
    response = confirm(client, auth_headers, view)
    assert response.status_code == 409, response.text
    assert db.query(Egreso).count() == 1 and db.query(Proveedor).count() == 0


@pytest.mark.parametrize("changes", [
    {"fecha": None}, {"proveedor": None}, {"monto": None}, {"metodo_pago": None},
    {"legible": False}, {"advertencias": ["Numero tapado"]}, {"monto": "NaN"},
    {"fecha": "31-feb-26"}, {"monto": "100.123"}, {"monto": 10},
])
def test_incomplete_or_uncertain_rows_cannot_be_imported(client, auth_headers, db, monkeypatch, changes):
    view = preview(client, auth_headers, monkeypatch, [row(**changes), row(fecha="02-sep-26")])
    assert view["filas"][0]["estado"] == "error"
    assert confirm(client, auth_headers, view, filas=[1]).status_code == 400
    assert confirm(client, auth_headers, view).json()["importados"] == 1
    assert db.query(Egreso).one().fecha == date(2026, 9, 2)


def test_totals_foreign_currency_and_unrecognized_document(monkeypatch, client, auth_headers):
    assert parsed([row(es_total=True)])["filas"][0]["omitida"] is True
    assert parsed(moneda="otra")["filas"][0]["errores"]
    assert parsed(moneda="no_visible")["advertencias"]
    assert parsed([]).get("error")
    assert parsed([row()] * 151).get("error")
    monkeypatch.setattr(egresos, "extraer_tabla_gastos", lambda *args: {"error": "Imagen ilegible"})
    assert client.post(PATH + "foto/previsualizar", headers=auth_headers,
                       files={"archivo": ("tabla.png", photo())}).status_code == 422


def test_incomplete_rows_preserve_other_legible_cells_for_manual_review():
    incomplete = parsed([row(monto=None, metodo_pago="A CREDITO")])["filas"][0]
    assert incomplete["errores"] and "monto" not in incomplete["datos"]
    assert incomplete["datos"]["fecha"] == "2026-09-01"
    assert incomplete["datos"]["proveedor"] == "Proveedor sintetico"
    assert incomplete["datos"]["metodo_pago"] == "credito"


def test_photo_permission_mime_and_options_checks(client, auth_headers, db, admin_user, monkeypatch):
    assert client.post(PATH + "foto/previsualizar", files={"archivo": ("a.png", photo())}).status_code == 401
    assert client.post(PATH + "foto/previsualizar", headers=auth_headers, files={"archivo": ("a.png", b"bad")}).status_code == 400
    assert client.post(PATH + "foto/previsualizar", headers=auth_headers, files={"archivo": ("a.png", photo())},
                       data={"opciones": '{"categoria":"inventada"}'}).status_code == 400
    admin_user.rol = RolUsuario.CONSULTA
    db.commit()
    assert client.post(PATH + "foto/previsualizar", headers=auth_headers, files={"archivo": ("a.png", photo())}).status_code == 403


def test_correcting_an_unreadable_row_resigns_without_another_ocr_call(client, auth_headers, db, monkeypatch):
    view = preview(client, auth_headers, monkeypatch, [row(monto=None, legible=False), row(fecha="02-sep-26")])
    monkeypatch.setattr(egresos, "extraer_tabla_gastos", lambda *args: pytest.fail("No se debe repetir el OCR"))
    correction = {"fila": 1, "fecha": "2026-09-01", "proveedor": "Proveedor sintetico",
                  "monto": "190.25", "metodo_pago": "transferencia"}
    revised = client.post(PATH + "foto/revisar", headers=auth_headers,
                          json={"token": view["token"], "correcciones": [correction]})
    assert revised.status_code == 200, revised.text
    revised = revised.json()
    assert [f["estado"] for f in revised["filas"]] == ["lista", "lista"]
    assert revised["filas"][0]["datos"]["monto"] == "190.25"
    assert revised["filas"][0]["datos"]["ocr_payload"]["original"]["monto"] == ""
    assert revised["filas"][0]["datos"]["ocr_payload"]["corregida"] is True
    assert confirm(client, auth_headers, revised).json()["importados"] == 2
    assert db.query(Egreso).count() == 2


def test_photo_corrections_cannot_skip_duplicates_or_change_a_registered_row(client, auth_headers, db, monkeypatch):
    view = preview(client, auth_headers, monkeypatch, [row(), row(fecha="02-sep-26")])
    assert confirm(client, auth_headers, view, filas=[1]).status_code == 200
    second_view = preview(client, auth_headers, monkeypatch, [row(), row(fecha="02-sep-26")])
    correction = {"fila": 1, "fecha": "2026-09-01", "proveedor": "Alterado",
                  "monto": "190.25", "metodo_pago": "transferencia"}
    assert client.post(PATH + "foto/revisar", headers=auth_headers,
                       json={"token": second_view["token"], "correcciones": [correction]}).status_code == 409
    correction.update(fila=2, fecha="2026-09-01", proveedor="Proveedor sintetico", monto="178.49")
    revised = client.post(PATH + "foto/revisar", headers=auth_headers,
                          json={"token": view["token"], "correcciones": [correction]}).json()
    assert revised["filas"][1]["estado"] == "duplicado"
    assert confirm(client, auth_headers, revised, filas=[2]).status_code == 409
    correction["fila"] = 999
    assert client.post(PATH + "foto/revisar", headers=auth_headers,
                       json={"token": view["token"], "correcciones": [correction]}).status_code == 422


def test_matching_amount_and_date_catches_misread_supplier(client, auth_headers, db, monkeypatch):
    db.add(Egreso(concepto="Servicio", proveedor="Proveedor sintetico", monto="178.49",
                  fecha=date(2026, 9, 1), metodo_pago="tarjeta", categoria="operativo"))
    db.commit()
    view = preview(client, auth_headers, monkeypatch, [row(proveedor="Proveed0r sintetico")])
    assert view["filas"][0]["estado"] == "duplicado"
    assert confirm(client, auth_headers, view, filas=[1]).status_code == 409


def test_structured_table_ocr_uses_existing_bounded_provider(monkeypatch):
    calls = []
    monkeypatch.setattr(ocr.settings, "ANTHROPIC_API_KEY", "synthetic-only")
    raw = {"error": "", "moneda": "MXN", "advertencias": [], "filas": [row()]}

    def post(url, **kwargs):
        calls.append(kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(raw)}]})

    monkeypatch.setattr(ocr.httpx, "post", post)
    result = ocr.extraer_tabla_gastos(photo(), "image/png")
    assert result["tipo"] == "foto" and len(result["documento_id"]) == 64
    assert calls[0]["json"]["output_config"]["format"]["schema"] == photos.TABLE_SCHEMA
    assert calls[0]["json"]["max_tokens"] == 16384
    assert "no confiable" in calls[0]["json"]["system"]


def test_table_preprocessing_splits_and_enlarges_without_changing_ticket_behavior():
    source = photo()
    ticket, _ = ocr.preparar_documento(source, "image/png")
    table, _ = ocr.preparar_documento(source, "image/png", tabla=True)
    assert len(ticket) == 1 and len(table) == 3
    with Image.open(BytesIO(base64.b64decode(ticket[0]["source"]["data"]))) as image:
        assert image.size == (500, 800)
    for block in table:
        with Image.open(BytesIO(base64.b64decode(block["source"]["data"]))) as image:
            assert image.width == 1000
            assert image.height < 600
            assert not image.getexif()
