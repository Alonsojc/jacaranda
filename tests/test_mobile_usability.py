"""Regresiones de usabilidad para la operacion diaria en iPad y iPhone."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def segment_between(text: str, start: str, end: str) -> str:
    start_idx = text.index(start)
    end_idx = text.index(end, start_idx)
    return text[start_idx:end_idx]


def test_mobile_form_controls_are_large_enough_for_ios():
    html = read_text("docs/index.html")

    assert "@media(pointer:coarse)" in html
    assert 'input:not([type="checkbox"]):not([type="radio"]),select,textarea{font-size:16px!important}' in html
    assert 'input:not([type="checkbox"]):not([type="radio"]),select,textarea{min-height:44px;font-size:16px!important}' in html
    assert "button:not(.password-toggle),input" in html
    assert "min-height:44px" in html
    assert ".cobrar,.limpiar,.wa-btn,.pbtn,.tab,.mm-link,.sales-mode-btn,.action-btn{min-height:48px}" in html
    assert ".catalog-icon-btn,.pos-tax-toggle{min-height:48px}" in html
    assert ".qty-btn{width:44px;height:44px}" in html
    assert ".pmt{grid-template-columns:repeat(2,minmax(0,1fr))!important}" in html
    assert "#cafeteria>.row.r4{grid-template-columns:repeat(2,minmax(0,1fr))!important" in html
    assert "#ped>.row.r3{grid-template-columns:repeat(3,minmax(0,1fr))!important" in html


def test_mobile_menu_is_grouped_and_empty_groups_follow_permissions():
    html = read_text("docs/index.html")
    visibility = segment_between(
        html,
        "function actualizarVisibilidadModulos",
        "function nuevaClaveIdempotencia",
    )

    assert 'data-mobile-section="operacion"' in html
    assert 'data-mobile-section="control"' in html
    assert 'data-mobile-section="configuracion"' in html
    assert "Trabajo diario" in html
    assert "Control y reportes" in html
    assert "Configuraci&oacute;n" in html
    assert "document.querySelectorAll('[data-mobile-section]')" in visibility
    assert "section.hidden" in visibility


def test_pos_mobile_ticket_does_not_jump_away_from_products():
    html = read_text("docs/index.html")
    add_segment = segment_between(html, "function add(id, n, pr)", "function redondearCentavosMitadPar")

    assert 'id="pos-cart-toggle"' in html
    assert 'id="pos-ticket-panel"' in html
    assert 'id="pos-ticket-overlay"' in html
    assert "function openMobileTicket" in html
    assert "function closeMobileTicket" in html
    assert "pulseMobileTicketBar();" in add_segment
    assert "scrollIntoView" not in add_segment
    assert ".mobile-cart-bar:not([hidden]){display:flex}" in html
    assert "max-height:88dvh" in html
    assert '<button type="button" class="pbtn sel" id="pm-ef"' in html
    assert '<button type="button" class="pbtn sel" id="caf-pm-trans"' in html


def test_pos_draft_is_scoped_to_user_and_cleared_on_logout():
    html = read_text("docs/index.html")
    core = read_text("docs/js/jacaranda-core.js")
    restore = segment_between(html, "function restorePosDraft", "function updateMobileTicketBar")
    logout = segment_between(html, "function cerrarSesion(opciones)", "async function confirmarCerrarSesion")

    assert "var POS_DRAFT_KEY = 'jacaranda_pos_draft'" in html
    assert "POS_DRAFT_MAX_AGE_MS = 12 * 60 * 60 * 1000" in html
    assert "draft.owner !== owner" in restore
    assert "draft.items.map" in restore
    assert "qty > 999" in restore
    assert "idempotencyKey: _ventaIdempotencyKey || null" in html
    assert "_ventaIdempotencyKey = /^venta-[A-Za-z0-9-]{8,190}$/.test(savedSaleKey)" in restore
    sale = segment_between(html, "function procesarVenta()", "function esperarPagoClip")
    assert sale.index("savePosDraft();") < sale.index("api('POST', '/punto-de-venta/ventas', body,")
    assert "function reconcilePosDraftWithProducts" in html
    assert "reconcilePosDraftWithProducts(prods);" in html
    assert "reconcilePosDraftWithProducts(cached);" in html
    assert "savePosDraft();" in html
    assert "restorePosDraft(u);" in html
    assert "clearPosDraft();" in logout
    assert "'jacaranda_pos_draft'" in core


def test_feedback_is_readable_and_old_toasts_do_not_hide_new_messages():
    html = read_text("docs/index.html")
    toast_segment = segment_between(html, "function toast(msg, isErr)", "function esArchivoLocal")

    assert 'id="toast" role="status" aria-live="polite" aria-atomic="true"' in html
    assert ".toast{" in html and "pointer-events:none" in html
    assert "if (_toastTimer) clearTimeout(_toastTimer)" in toast_segment
    assert "isErr ? 'alert' : 'status'" in toast_segment
    assert "isErr ? 5000 : 3200" in toast_segment


def test_hidden_ingredient_purchase_has_no_dead_egresos_action():
    html = read_text("docs/index.html")
    egresos = segment_between(html, '<div class="page" id="egresos">', '<div class="page" id="listas">')

    assert "Compra de ingredientes" not in egresos
    assert "invTab('compras')" not in egresos


def test_sales_are_one_touch_first_module_with_three_clear_menus():
    html = read_text("docs/index.html")
    nav = segment_between(html, '<div class="nav-links">', '</nav>')
    operation = segment_between(nav, '<a>Operaci&oacute;n</a>', '<div class="nav-group" data-roles-group="ADMINISTRADOR,GERENTE,CONTADOR,CONSULTA">')
    cafeteria_header = segment_between(
        html,
        '<div class="page" id="cafeteria">',
        '<div class="row r4" style="margin-bottom:1rem">',
    )

    assert nav.index('class="sales-nav-link"') < nav.index('data-pg="dash"')
    assert "Punto de venta" in nav
    assert 'data-pg="pos" onclick="go(\'pos\')"' not in operation
    assert 'data-pg="cafeteria"' not in operation
    assert html.count('data-sales-mode="mostrador"') == 2
    assert html.count('data-sales-mode="cafeterias"') == 2
    assert html.count('data-sales-mode="uber_eats"') == 2
    assert '<div class="page-actions">' not in cafeteria_header
    assert '</div>\n<div class="cafeteria-tools"' in cafeteria_header
    assert "async function cambiarModoVenta" in html
    assert "canal: _posCanal" in html
    assert ".nav-dd a{display:flex;align-items:center;min-height:48px" in html
    assert ".pi{min-height:170px" in html


def test_products_offer_guided_codes_presentations_uber_price_and_packaging_catalog():
    html = read_text("docs/index.html")

    assert 'id="mnp-precio-uber"' in html
    assert 'id="mep-precio-uber"' in html
    assert "precio_uber_eats: precioUberRaw ? parseFloat(precioUberRaw) : null" in html
    assert "function nuevaPresentacion" in html
    assert "/inventario/productos/codigo-sugerido" in html
    assert "/inventario/productos/codigo-disponible" in html
    assert "<th>Uber Eats</th>" in html
    assert "<th>C&oacute;digo</th>" in html
    assert "Cajas y empaques</span>" in html
    assert 'id="l-empaques"' in html
    assert "/inventario/empaques" in html


def test_product_families_are_explicit_instead_of_inferred_from_names():
    html = read_text("docs/index.html")

    assert 'id="l-familias"' in html
    assert 'id="mnp-familia"' in html
    assert 'id="mep-familia"' in html
    assert 'id="mnp-presentacion"' in html
    assert 'id="mep-presentacion"' in html
    assert "function grupoFormalProducto" in html
    assert "key: 'familia-' + producto.familia_id" in html
    assert "/inventario/familias-producto" in html
    assert "/inventario/productos/' + id + '/crear-familia" in html
