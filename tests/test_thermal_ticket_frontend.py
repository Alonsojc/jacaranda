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


def test_product_ticket_lines_keep_subtotal_next_to_quantity_and_name():
    assert "function formatoLineaProductoTicket(producto)" in HTML
    assert "fmtQty(producto.cantidad) + 'x  $' + fmt(producto.subtotal)" in HTML
    assert "txt += formatoLineaProductoTicket(p) + '\\n';" in HTML
    assert "detalle.push(formatoLineaProductoTicket(producto));" in HTML
    assert "texto(formatoLineaProductoTicket(producto), 14, {ancho: contenido});" in HTML


def test_thermal_ticket_uses_native_ios_schema_with_image_fallback():
    thermal = _segment("function compartirTicketConThermer", "// ─── Fotos masivas")

    assert "esDispositivoAppleMovil()" in thermal
    assert "abrirThermerNativo(_ultimoTicket);" in thermal
    assert "cerrarModal('modal-ticket');" in thermal
    assert "new File([ticketImagen.blob]" in thermal
    assert "{type: 'image/png'}" in thermal
    assert "navigator.canShare({files: [archivo]})" in thermal
    assert "navigator.share({" in thermal
    assert "cerrarModal('modal-ticket');" in thermal
    assert "En la hoja de compartir, elige Thermer y abre Image" in thermal
    assert "window.print()" not in thermal


def test_thermal_ticket_uses_documented_thermer_scheme_with_native_text_entries():
    thermal = _segment("function textoThermer", "function nombreArchivoTicketTermico")

    assert "texto.normalize('NFD')" in thermal
    assert "function textoThermerBloque" in thermal
    assert "join('<br />')" in thermal
    assert "function datosThermerEnBloques" in thermal
    assert "var entradas = {};" in thermal
    assert "type: 0," in thermal
    assert "content: textoThermerBloque(bloque.lineas)" in thermal
    assert "window.location.href = 'thermer://?data=' + datos;" in thermal
    assert "// Margen final para que la guillotina manual no corte la última línea." in thermal
    assert "return datosThermerEnBloques(bloques);" in thermal


def test_cash_closing_can_print_with_the_native_thermer_schema():
    thermal = _segment("function crearDatosCorteThermer", "function nombreArchivoTicketTermico")

    assert "encabezado.push('CORTE DE CAJA')" in thermal
    assert "agregarFilaThermer(ventas, 'TOTAL EFECTIVO'" in thermal
    assert "agregarFilaThermer(ventas, 'TOTAL DEL DIA'" in thermal
    assert "agregarFilaThermer(resumen, 'Diferencia'" in thermal
    assert "return datosThermerEnBloques(bloques);" in thermal
    assert "function imprimirCorteThermer" in thermal
    assert "window.location.href = 'thermer://?data=' + datos;" in thermal
    assert "function imprimirUltimoCorte" in thermal
