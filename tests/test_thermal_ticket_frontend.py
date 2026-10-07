"""Regresiones para imprimir tickets de 58 mm con Easy POS Print."""

from pathlib import Path


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def _segment(start: str, end: str) -> str:
    return HTML[HTML.index(start):HTML.index(end, HTML.index(start))]


def test_ticket_modal_only_offers_easy_pos_print():
    modal = _segment("<!-- MODAL: Ticket confirmación / ver ticket -->", "<!-- MODAL: Usuario -->")
    assert 'id="mt-easy-pos-print-btn"' in modal
    assert "Enviar a Easy POS" in modal
    assert 'onclick="enviarTicketAEasyPosPrint()"' in modal
    assert "Guardar PDF" in modal
    assert 'onclick="imprimirTicket()"' not in modal
    assert "Thermer" not in HTML
    assert "thermer://" not in HTML


def test_product_lines_keep_subtotal_next_to_quantity_and_name():
    assert "fmtQty(producto.cantidad) + 'x  $' + fmt(producto.subtotal)" in HTML
    assert "txt += formatoLineaProductoTicket(p) + '\\n';" in HTML


def test_easy_pos_uses_direct_scheme_without_paid_autoprint_and_closes_modal():
    easy = _segment("function textoTicketParaEasyPos", "function compartirWhatsApp")
    assert "function copiarTicketParaEasyPosPrint()" in easy
    assert "easyposprint://print?text=' + encodeURIComponent(texto)" in easy
    assert "&paper=58&source=' + encodeURIComponent('Jacaranda')" in easy
    assert "cerrarModal('modal-ticket');" in easy
    assert "window.location.href = url;" in easy
    assert "autoprint=1" not in easy
    assert "txt += '\\n\\n\\n';" in easy
    assert "fallbackCopy(txt, mensajeExito);" in easy


def test_cut_print_uses_plain_text_and_marks_unregistered_preview():
    thermal = _segment("function textoCorteParaEasyPos", "// ─── Fotos masivas")
    assert "PROVISIONAL - NO REGISTRADO" in thermal
    assert "'TOTAL DEL TURNO'" in thermal
    assert "'Retiro a resguardo'" in thermal
    assert "'Recibido por (resguardo):'" in thermal
    assert "'\\n\\n\\n\\n'" in thermal
    assert "function imprimirCorteActual" in thermal
    assert "var guardado = corteGuardadoParaExportar();" in thermal
    assert "_corteVistaLista" in thermal
    assert "'Sin contar'" in thermal
    assert "easyposprint://print?text=' + encodeURIComponent(textoCorteParaEasyPos(corte))" in thermal
    assert 'onclick="imprimirCorteActual()"' in HTML
    assert 'onclick="exportarCorte()"' not in HTML
