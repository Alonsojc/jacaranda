"""Regresiones para el envío de tickets de 58 mm desde iPad/iPhone."""

from pathlib import Path


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def _segment(start: str, end: str) -> str:
    return HTML[HTML.index(start):HTML.index(end, HTML.index(start))]


def test_ticket_modal_uses_thermal_share_action_instead_of_airprint():
    modal = _segment("<!-- MODAL: Ticket confirmación / ver ticket -->", "<!-- MODAL: Nuevo Usuario -->")

    assert 'id="mt-thermal-print-btn"' in modal
    assert "Enviar a Thermer" in modal
    assert 'onclick="compartirTicketConThermer()"' in modal
    assert "Guardar PDF" in modal
    assert 'onclick="imprimirTicket()"' not in modal


def test_thermal_ticket_is_a_48mm_printable_image_for_58mm_paper():
    thermal = _segment("function crearTicketTermicoImagen", "// ─── Fotos masivas")

    assert "var ancho = 384;" in thermal
    assert "384 puntos equivalen a los 48 mm imprimibles" in thermal
    assert "final.toDataURL('image/png')" in thermal
    assert "filename: nombreArchivoTicketTermico(tk)" in thermal
    assert "return 'ticket_' + folio + '.png';" in HTML


def test_thermal_ticket_uses_ios_share_sheet_and_not_airprint():
    thermal = _segment("function compartirTicketConThermer", "// ─── Fotos masivas")

    assert "new File([ticketImagen.blob]" in thermal
    assert "{type: 'image/png'}" in thermal
    assert "navigator.canShare({files: [archivo]})" in thermal
    assert "navigator.share({" in thermal
    assert "cerrarModal('modal-ticket');" in thermal
    assert "En la hoja de compartir, elige Thermer y abre Image" in thermal
    assert "window.print()" not in thermal
