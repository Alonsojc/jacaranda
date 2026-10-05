"""Regresiones de las acciones de corte de caja desde iPad/iPhone."""

from pathlib import Path
import shutil
import subprocess

import pytest


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def test_cash_closing_surface_has_print_and_lifecycle_actions():
    assert 'id="modal-corte-registrado"' in HTML
    assert "Imprimir corte" in HTML
    assert 'id="modal-corte-editar"' in HTML
    assert "function guardarEdicionCorte" in HTML
    assert "function reabrirCorte" in HTML
    assert "function cancelarCorte" in HTML
    assert "Último corte: turno" in HTML
    assert "Ventas del turno" in HTML
    assert "Registrar corte · Turno" in HTML
    assert "/punto-de-venta/corte-caja/ventas?fecha=" in HTML
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


def test_cash_handover_controls_and_print_paths():
    for prefix in ("c", "mce"):
        for field in ("retiro", "fondo-entregado", "recibido-por"):
            assert f'id="{prefix}-{field}"' in HTML
    assert "function actualizarResguardoCorte" in HTML
    assert "function datosEntregaCorte" in HTML
    assert "Recibido por (resguardo)" in HTML
    assert "imprimirCorteEasyPos(_ultimoCorteRegistrado)" in HTML
    assert "imprimirCorteEasyPos(' + corte.id" in HTML
    assert "corte.fondo_entregado != null" in HTML
    assert "corte.retiros" in HTML
    assert "corte.recibido_por" in HTML
    assert "r.entrega_efectivo_disponible !== true" in HTML


def test_cash_handover_math_validation_and_receipt_text():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute frontend helpers")

    def section(start, end):
        offset = HTML.index(start)
        return HTML[offset:HTML.index(end, offset)]

    helpers = section("function actualizarResguardoCorte", "function realizarCorte")
    thermal = section("function textoTicketTermico", "function esDispositivoAppleMovil")
    receipt = section("function crearDatosCorteThermer", "function imprimirCorteThermer")
    easy = section("function textoCorteParaEasyPos", "function imprimirCorteEasyPos")
    js = r"""
const assert = require('node:assert/strict');
const fields = {};
const document = {getElementById: id => fields[id]};
function fmt(n) { return Number(n).toFixed(2); }
function formatearInstanteOperacion() { return '05/10/2026 12:00'; }
""" + helpers + thermal + receipt + easy + r"""
fields['c-real'] = {value: '5000'};
fields['c-fondo-entregado'] = {value: '2000'};
fields['c-retiro'] = {value: ''};
fields['c-recibido-por'] = {value: '  Alonso  '};
actualizarResguardoCorte('c');
assert.equal(fields['c-retiro'].value, '3000.00');
assert.deepEqual(datosEntregaCorte('c', 5000), {
  retiros: 3000, fondo_entregado: 2000, recibido_por: 'Alonso'
});
fields['c-fondo-entregado'].value = '6000';
assert.throws(() => datosEntregaCorte('c', 5000));
actualizarResguardoCorte('c');
assert.equal(fields['c-retiro'].value, '');
fields['c-fondo-entregado'].value = '2000';
fields['c-recibido-por'].value = '   ';
assert.throws(() => datosEntregaCorte('c', 5000));
assert.equal(datosEntregaCorte('c', 2000).retiros, 0);
fields['c-fondo-entregado'].value = '2000.10';
fields['c-recibido-por'].value = 'Alonso';
assert.equal(datosEntregaCorte('c', 5000.30).retiros, 3000.2);
fields['mce-fondo-entregado'] = {value: ''};
fields['mce-recibido-por'] = {value: ''};
assert.equal(datosEntregaCorte('mce', 5000).fondo_entregado, null);
const cut = {id: 1, turno: 1, fondo_inicial: 2000, total_ventas_efectivo: 3000,
  efectivo_esperado: 5000, efectivo_real: 5000, diferencia: 0, total_ventas: 3000,
  retiros: 3000, fondo_entregado: 2000, recibido_por: 'Alonso'};
const text = textoCorteParaEasyPos(cut);
assert.ok(text.includes('Retiro a resguardo'));
assert.ok(text.includes('$3000.00'));
assert.ok(text.includes('Fondo entregado al siguiente turno\n$2000.00'));
assert.ok(text.includes('Recibido por (resguardo):\nAlonso'));
assert.ok(text.endsWith('\n\n\n'));
delete cut.fondo_entregado;
assert.ok(!textoCorteParaEasyPos(cut).includes('Retiro a resguardo'));
"""
    result = subprocess.run([node, "-e", js], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
