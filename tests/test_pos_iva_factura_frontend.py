"""Checks frontend wiring for POS optional invoice IVA."""

from pathlib import Path


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def test_pos_ticket_iva_is_optional_by_default():
    assert "IVA 16%</span><span id=\"tiva\"" not in HTML
    assert "id=\"tiva-label\">IVA</span>" in HTML
    assert "id=\"pos-iva-factura-btn\"" in HTML
    assert "Agregar 8% IVA para factura" in HTML
    assert "Sin IVA por default" in HTML


def test_pos_checkout_modal_exposes_invoice_iva_toggle():
    assert "id=\"mc-iva-factura-btn\"" in HTML
    assert "id=\"mc-iva-factura-resumen\"" in HTML
    assert "function togglePosFacturaIva()" in HTML
    assert "Quitar IVA factura 8%" in HTML


def test_pos_sale_payload_preserves_invoice_iva_rate_online_and_offline():
    assert "iva_factura_tasa: _posFacturaIvaActiva ? POS_FACTURA_IVA_TASA : 0" in HTML
    assert "iva_factura_tasa: venta.iva_factura_tasa || 0" in HTML
    assert "iva_factura_tasa: body.iva_factura_tasa || 0" in HTML
    assert "posIvaTasaLinea" in HTML


def test_invoice_iva_does_not_depend_on_product_tax_configuration():
    assert "function posIvaTasaLinea()" in HTML
    assert "return _posFacturaIvaActiva ? POS_FACTURA_IVA_TASA : 0;" in HTML
    assert "(item.iv || 0) > 0" not in HTML


def test_product_forms_and_table_do_not_expose_legacy_iva_selector():
    assert 'id="mnp-iva"' not in HTML
    assert 'id="mep-iva"' not in HTML
    assert "<th>M&iacute;n</th><th>IVA</th>" not in HTML
    assert "Precio Cafeteria,Costo,Stock,Minimo,IVA,Unidad" not in HTML
