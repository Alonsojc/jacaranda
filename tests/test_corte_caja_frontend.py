"""Regresiones de las acciones de corte de caja desde iPad/iPhone."""

from pathlib import Path


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def test_cash_closing_surface_has_print_and_lifecycle_actions():
    assert 'id="modal-corte-registrado"' in HTML
    assert "Imprimir corte" in HTML
    assert 'id="modal-corte-editar"' in HTML
    assert "function guardarEdicionCorte" in HTML
    assert "function reabrirCorte" in HTML
    assert "function cancelarCorte" in HTML
    assert "Corte cerrado para esta fecha" in HTML
    assert "function apiProtegidaConPasswordAdmin" in HTML
    assert "apiProtegidaConPasswordAdmin('PUT'" in HTML
    assert "apiProtegidaConPasswordAdmin('POST'" in HTML


def test_cash_closing_actions_require_reason_and_confirmation():
    start = HTML.index("async function cambiarEstadoCorte")
    end = HTML.index("function reabrirCorte", start)
    lifecycle = HTML[start:end]

    assert "solicitarEntrada" in lifecycle
    assert "confirmarAccion" in lifecycle
    assert "motivo.length < 5" in lifecycle
    assert "apiProtegidaConPasswordAdmin('POST'" in lifecycle


def test_cash_closing_controls_are_compact_and_touchable():
    assert "#btn-update-app{width:48px;min-width:48px;height:48px" in HTML
    assert 'id="c-corte-acciones" class="corte-actions"' in HTML
    assert "action-buttons corte-actions" in HTML
    assert ".corte-actions .action-btn{min-width:0" in HTML
