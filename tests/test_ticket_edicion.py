"""Ticket corrections use isolated inventory and cash records only."""

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.auditoria import LogAuditoria
from app.models.inventario import Ingrediente, MovimientoInventario, Producto, UnidadMedida
from app.models.venta import CorteCaja, EstadoVenta, MetodoPago, PagoVenta, Venta
from app.schemas.venta import CorteCajaCreate, DetalleVentaCreate, VentaCreate, VentaEdicion
from app.services import ticket_edicion_service as svc
from app.services.venta_service import (
    _fecha_hora_operacion, cambiar_estado_corte_caja, generar_ticket, procesar_venta,
    realizar_corte_caja, resumen_corte_caja,
)


@pytest.fixture
def ticket(db, admin_user):
    cajas = [Ingrediente(nombre=f"Caja test {i}", unidad_medida=UnidadMedida.CAJA,
                         es_empaque=True, stock_actual=20) for i in range(2)]
    db.add_all(cajas)
    db.flush()
    productos = [Producto(codigo=f"EDIT-{i}", nombre=f"Producto test {i}", precio_unitario=p,
                          stock_actual=10, caja_ingrediente_id=cajas[i].id, caja_cantidad=1)
                 for i, p in enumerate([Decimal("100"), Decimal("450")])]
    db.add_all(productos)
    db.commit()
    venta = procesar_venta(db, VentaCreate(monto_recibido=Decimal("500"), detalles=[
        DetalleVentaCreate(producto_id=productos[0].id, cantidad=2, descuento=Decimal("10")),
    ]), admin_user.id)
    return venta, productos, cajas


def payload(venta, modo="productos", **change):
    return {"modo": modo, "revision": venta.edicion_revision, "motivo": "Corregir captura de prueba",
            "detalles": [{"id": venta.detalles[0].id, **change}]}


def corregir(db, admin, venta, modo="productos", **change):
    return svc.editar_ticket(db, venta.id, VentaEdicion(**payload(venta, modo, **change)), admin.id)


def test_producto_conserva_importes_y_corrige_stock_y_empaque(db, admin_user, ticket):
    venta, productos, cajas = ticket
    old = (venta.total, venta.subtotal, venta.descuento, venta.monto_recibido, venta.cambio)
    venta = corregir(db, admin_user, venta, producto_id=productos[1].id)
    assert (venta.total, venta.subtotal, venta.descuento, venta.monto_recibido, venta.cambio) == old
    assert venta.detalles[0].precio_unitario == Decimal("100")
    assert venta.detalles[0].producto_nombre == productos[1].nombre
    assert [p.stock_actual for p in productos] == [Decimal("10"), Decimal("8")]
    assert [c.stock_actual for c in cajas] == [Decimal("20"), Decimal("18")]
    assert venta.edicion_revision == 1
    assert generar_ticket(db, venta.id)["productos"][0]["nombre"] == productos[1].nombre
    audit = db.query(LogAuditoria).filter_by(accion="editar_ticket").one()
    assert audit.motivo == "Corregir captura de prueba"
    assert json.loads(audit.datos_anteriores)["detalles"][0]["producto_id"] == productos[0].id
    assert json.loads(audit.datos_nuevos)["detalles"][0]["producto_id"] == productos[1].id


def test_precio_corrige_totales_y_cambio_sin_mover_stock(db, admin_user, ticket):
    venta, productos, cajas = ticket
    count = db.query(MovimientoInventario).count()
    venta = corregir(db, admin_user, venta, "precios", precio_unitario="150.00")
    assert venta.total == Decimal("290")
    assert venta.cambio == Decimal("210")
    assert venta.descuento == Decimal("10")
    assert venta.detalles[0].producto_id == productos[0].id
    assert db.query(MovimientoInventario).count() == count
    assert [p.stock_actual for p in productos] == [Decimal("8"), Decimal("10")]
    assert [c.stock_actual for c in cajas] == [Decimal("18"), Decimal("20")]
    resumen = resumen_corte_caja(db, _fecha_hora_operacion(venta.fecha).date())
    assert resumen["total_ventas"] == Decimal("290")
    assert resumen["total_ventas_efectivo"] == Decimal("290")
    assert generar_ticket(db, venta.id)["total"] == "$290.00"


def test_precio_respeta_iva_y_pago_bbva(db, admin_user, ticket):
    venta, productos, _ = ticket
    venta.metodo_pago = MetodoPago.TARJETA_DEBITO
    from app.models.venta import TerminalPago
    venta.terminal = TerminalPago.BBVA
    venta.detalles[0].tasa_iva = Decimal(".08")
    pago = PagoVenta(venta=venta, metodo_pago=venta.metodo_pago, terminal=venta.terminal,
                     monto=venta.total, referencia="REFERENCIA-TEST")
    db.add(pago)
    db.commit()
    venta = corregir(db, admin_user, venta, "precios", precio_unitario="125.25")
    assert venta.subtotal == Decimal("240.50")
    assert venta.total_impuestos == Decimal("19.24")
    assert venta.total == Decimal("259.74")
    assert venta.monto_recibido == venta.total
    assert pago.monto == venta.total
    assert pago.referencia == "REFERENCIA-TEST"
    assert productos[0].stock_actual == Decimal("8")
    assert resumen_corte_caja(db, _fecha_hora_operacion(venta.fecha).date())["total_ventas_bbva"] == venta.total


@pytest.mark.parametrize("campo,valor", [("stock_actual", 1), ("activo", False)])
def test_rechazo_producto_es_atomico(db, admin_user, ticket, campo, valor):
    venta, productos, cajas = ticket
    setattr(productos[1], campo, valor)
    db.commit()
    count = db.query(MovimientoInventario).count()
    with pytest.raises(ValueError):
        corregir(db, admin_user, venta, producto_id=productos[1].id)
    assert venta.edicion_revision == 0
    assert venta.detalles[0].producto_id == productos[0].id
    assert productos[0].stock_actual == Decimal("8")
    assert cajas[0].stock_actual == Decimal("18")
    assert db.query(MovimientoInventario).count() == count
    assert db.query(LogAuditoria).filter_by(accion="editar_ticket").count() == 0


def test_no_puede_repetir_correccion_o_sobrescribir_otra(db, admin_user, ticket):
    venta, productos, _ = ticket
    data = VentaEdicion(**payload(venta, producto_id=productos[1].id))
    svc.editar_ticket(db, venta.id, data, admin_user.id)
    count = db.query(MovimientoInventario).count()
    with pytest.raises(svc.EdicionDesactualizada):
        svc.editar_ticket(db, venta.id, data, admin_user.id)
    assert db.query(MovimientoInventario).count() == count
    assert venta.edicion_revision == 1


@pytest.mark.parametrize("precio", ["300.00", "1.00"])
def test_precio_invalido_revierte_todos_los_cambios(db, admin_user, ticket, precio):
    venta, _, _ = ticket
    with pytest.raises(ValueError):
        corregir(db, admin_user, venta, "precios", precio_unitario=precio)
    assert venta.total == Decimal("190")
    assert venta.detalles[0].precio_unitario == Decimal("100")
    assert venta.edicion_revision == 0


@pytest.mark.parametrize("change", [
    {"producto_id": 1, "precio_unitario": "20"}, {"precio_unitario": "20"},
    {"producto_id": 1, "cantidad": 9}, {"producto_id": -1},
])
def test_esquema_separa_producto_precio_y_no_permite_cambiar_cantidad(change):
    with pytest.raises(ValidationError):
        VentaEdicion(modo="productos", revision=0, motivo="Prueba correcta", detalles=[{"id": 1, **change}])


@pytest.mark.parametrize("precio", ["-1", "NaN", "Infinity", "1.111", "999999999999"])
def test_esquema_rechaza_precio_invalido(precio):
    with pytest.raises(ValidationError):
        VentaEdicion(modo="precios", revision=0, motivo="Prueba correcta", detalles=[{"id": 1, "precio_unitario": precio}])


@pytest.mark.parametrize("campo,valor", [
    ("facturada", True), ("estado", EstadoVenta.CANCELADA), ("estado", EstadoVenta.PENDIENTE),
    ("pago_integrado", True), ("recompensa_lealtad_canjeada", True), ("canal", "uber_eats"),
])
def test_tickets_no_editables_se_rechazan(db, admin_user, ticket, campo, valor):
    venta, productos, _ = ticket
    setattr(venta, campo, valor)
    db.commit()
    assert svc.contexto_edicion(db, venta.id)["bloqueo"]
    with pytest.raises(ValueError):
        corregir(db, admin_user, venta, producto_id=productos[1].id)
    assert venta.edicion_revision == 0


def test_corte_cerrado_requiere_reabrir_y_no_se_modifica_su_fotografia(db, admin_user, ticket):
    venta, productos, _ = ticket
    corte = realizar_corte_caja(db, CorteCajaCreate(fondo_inicial=2000, efectivo_real=2190), admin_user.id)
    assert "Reabre primero" in svc.contexto_edicion(db, venta.id)["bloqueo"]
    with pytest.raises(ValueError, match="Reabre primero"):
        corregir(db, admin_user, venta, "precios", precio_unitario="120")
    cambiar_estado_corte_caja(db, corte.id, "reabierto", "Correccion de ticket", admin_user.id)
    corregir(db, admin_user, venta, "precios", precio_unitario="120")
    assert corte.total_ventas == Decimal("190")
    assert venta.total == Decimal("230")


def test_venta_del_turno_abierto_no_es_bloqueada_por_corte_anterior(db, admin_user, ticket):
    venta, _, _ = ticket
    corte = realizar_corte_caja(db, CorteCajaCreate(fondo_inicial=2000, efectivo_real=2190), admin_user.id)
    venta.fecha = corte.periodo_fin + timedelta(seconds=1)
    db.commit()
    assert svc.contexto_edicion(db, venta.id)["bloqueo"] is None


def test_api_exige_password_incluso_admin_y_audita_autorizacion(client, auth_headers, ticket, db):
    venta, productos, _ = ticket
    url = f"/api/v1/punto-de-venta/ventas/{venta.id}"
    body = payload(venta, producto_id=productos[1].id)
    assert client.patch(url, json=body, headers=auth_headers).status_code == 403
    headers = {**auth_headers, "X-Admin-Override-Password": "incorrecta", "X-Admin-Override-Motivo": "Corregir%20captura"}
    assert client.patch(url, json=body, headers=headers).status_code == 403
    headers["X-Admin-Override-Password"] = "test1234"
    resp = client.patch(url, json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["edicion_revision"] == 1
    assert client.patch(url, json=body, headers=headers).status_code == 409
    assert db.query(LogAuditoria).filter_by(accion="editar_ticket").count() == 1


def test_partida_ajena_y_duplicados_no_se_aceptan(db, admin_user, ticket):
    venta, productos, _ = ticket
    body = payload(venta, producto_id=productos[1].id)
    body["detalles"][0]["id"] = 999
    with pytest.raises(ValueError, match="no pertenece"):
        svc.editar_ticket(db, venta.id, VentaEdicion(**body), admin_user.id)
    body["detalles"] *= 2
    with pytest.raises(ValidationError):
        VentaEdicion(**body)


def test_pago_dividido_conserva_su_distribucion_en_cambio_de_producto(db, admin_user, ticket):
    venta, productos, _ = ticket
    db.add_all([PagoVenta(venta=venta, metodo_pago=m, monto=Decimal("95"))
                for m in (MetodoPago.EFECTIVO, MetodoPago.TRANSFERENCIA)])
    db.commit()
    with pytest.raises(ValueError, match="pago dividido"):
        corregir(db, admin_user, venta, "precios", precio_unitario="150")
    corregir(db, admin_user, venta, producto_id=productos[1].id)
    assert [p.monto for p in venta.pagos] == [Decimal("95"), Decimal("95")]


def test_cliente_conserva_puntos_y_no_admite_cambio_de_precio(db, admin_user, ticket):
    from app.models.cliente import Cliente

    venta, productos, _ = ticket
    cliente = Cliente(nombre="Cliente ficticio", puntos_acumulados=30, monto_lealtad_acumulado=1500)
    db.add(cliente)
    db.flush()
    venta.cliente_id = cliente.id
    db.commit()
    assert "lealtad" in svc.contexto_edicion(db, venta.id)["bloqueo_precios"]
    with pytest.raises(ValueError, match="lealtad"):
        corregir(db, admin_user, venta, "precios", precio_unitario="150")
    corregir(db, admin_user, venta, producto_id=productos[1].id)
    assert cliente.puntos_acumulados == 30
    assert cliente.monto_lealtad_acumulado == Decimal("1500")
    assert venta.total == Decimal("190")


def test_comprobante_sin_timbrar_tambien_bloquea_edicion(db, admin_user, ticket):
    from app.models.facturacion import CFDIComprobante, TipoComprobante

    venta, productos, _ = ticket
    comprobante = CFDIComprobante(
        venta=venta, serie="TEST", folio="1", fecha=venta.fecha,
        tipo_comprobante=TipoComprobante.INGRESO, forma_pago="01", metodo_pago="PUE",
        lugar_expedicion="00000", emisor_rfc="XAXX010101000", emisor_nombre="Prueba",
        emisor_regimen_fiscal="601", receptor_rfc="XAXX010101000", receptor_nombre="Prueba",
        receptor_regimen_fiscal="616", receptor_domicilio_fiscal="00000", receptor_uso_cfdi="S01",
        subtotal=venta.subtotal, total=venta.total,
    )
    db.add(comprobante)
    db.commit()
    assert not venta.facturada and comprobante.uuid is None
    assert "comprobante fiscal" in svc.contexto_edicion(db, venta.id)["bloqueo"]
    with pytest.raises(ValueError, match="comprobante fiscal"):
        corregir(db, admin_user, venta, producto_id=productos[1].id)
    assert venta.edicion_revision == 0


def test_cancelar_ticket_corregido_devuelve_el_producto_correcto(db, admin_user, ticket):
    from app.services.venta_service import cancelar_venta

    venta, productos, cajas = ticket
    corregir(db, admin_user, venta, producto_id=productos[1].id)
    cancelar_venta(db, venta.id, admin_user.id, "Cancelar ticket ficticio")
    assert [p.stock_actual for p in productos] == [Decimal("10"), Decimal("10")]
    assert [c.stock_actual for c in cajas] == [Decimal("20"), Decimal("20")]


def test_intercambiar_partidas_sin_stock_extra(db, admin_user, ticket):
    venta, productos, cajas = ticket
    # A separate fictional sale consumes both remaining products.
    productos[0].stock_actual = 1
    productos[1].stock_actual = 1
    db.commit()
    venta = procesar_venta(db, VentaCreate(monto_recibido=600, detalles=[
        DetalleVentaCreate(producto_id=p.id, cantidad=1) for p in productos
    ]), admin_user.id)
    old_total = venta.total
    cambios = [{"id": d.id, "producto_id": productos[1 - i].id} for i, d in enumerate(venta.detalles)]
    svc.editar_ticket(db, venta.id, VentaEdicion(modo="productos", revision=0,
                      motivo="Intercambiar productos de prueba", detalles=cambios), admin_user.id)
    assert venta.total == old_total
    assert [p.stock_actual for p in productos] == [Decimal("0"), Decimal("0")]


def test_empaque_insuficiente_revierte_producto_y_auditoria(db, admin_user, ticket):
    venta, productos, cajas = ticket
    cajas[1].stock_actual = 0
    db.commit()
    count = db.query(MovimientoInventario).count()
    with pytest.raises(ValueError, match="Stock insuficiente"):
        corregir(db, admin_user, venta, producto_id=productos[1].id)
    assert productos[0].stock_actual == Decimal("8")
    assert productos[1].stock_actual == Decimal("10")
    assert cajas[0].stock_actual == Decimal("18")
    assert db.query(MovimientoInventario).count() == count


def test_cajero_necesita_password_admin_y_permiso_editar(client, auth_headers, admin_user, ticket, db):
    from app.core.security import create_access_token, get_password_hash
    from app.models.usuario import RolUsuario, Usuario

    user = Usuario(nombre="Cajero prueba", email="cashier@test.invalid", rol=RolUsuario.CAJERO,
                   hashed_password=get_password_hash("test-only-password"))
    db.add(user)
    db.commit()
    headers = {"Authorization": "Bearer " + create_access_token({"sub": str(user.id)}),
               "X-Admin-Override-Password": "test1234", "X-Admin-Override-Motivo": "Prueba%20de%20autorizacion"}
    venta, productos, _ = ticket
    url = f"/api/v1/punto-de-venta/ventas/{venta.id}"
    body = payload(venta, producto_id=productos[1].id)
    assert client.patch(url, json=body, headers=headers).status_code == 200
    user.permisos_modulos = {"pos": "ver"}
    db.commit()
    assert client.get(url + "/edicion", headers=headers).status_code == 403
    assert client.patch(url, json=body, headers=headers).status_code == 403


def test_price_change_with_more_cash_received_keeps_stock(db, admin_user, ticket):
    venta, _, _ = ticket
    body = {**payload(venta, "precios", precio_unitario="300"), "monto_recibido": "600"}
    svc.editar_ticket(db, venta.id, VentaEdicion(**body), admin_user.id)
    assert venta.total == Decimal("590")
    assert venta.cambio == Decimal("10")


def test_revision_and_cut_snapshot_are_serialized_on_sqlite_file(tmp_path, admin_user):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    from app.models.usuario import Usuario
    from app.services.venta_service import bloquear_dia_caja

    engine = create_engine(f"sqlite:///{tmp_path / 'corrections.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    started, completed = Event(), Event()
    with factory() as first:
        user = Usuario(nombre="Admin prueba", email="thread@test.invalid", rol=admin_user.rol,
                       hashed_password=admin_user.hashed_password)
        product = Producto(codigo="CONCURRENT", nombre="Prueba concurrente", precio_unitario=100, stock_actual=10)
        first.add_all([user, product])
        first.commit()
        user_id = user.id
        venta = procesar_venta(first, VentaCreate(monto_recibido=500,
                               detalles=[DetalleVentaCreate(producto_id=product.id, cantidad=1)]), user_id)
        body = VentaEdicion(**payload(venta, "precios", precio_unitario="150"))
        bloquear_dia_caja(first, _fecha_hora_operacion(venta.fecha).date())

        def cerrar_turno():
            with factory() as second:
                started.set()
                corte = realizar_corte_caja(second, CorteCajaCreate(fondo_inicial=2000, efectivo_real=2150), user_id)
                completed.set()
                return corte.total_ventas

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(cerrar_turno)
            assert started.wait(2)
            assert not completed.wait(.1)
            svc.editar_ticket(first, venta.id, body, user_id)
            assert future.result(timeout=5) == Decimal("150")
        with pytest.raises(ValueError, match="Reabre primero"):
            svc.editar_ticket(first, venta.id, VentaEdicion(**payload(venta, "precios", precio_unitario="160")), user_id)
    engine.dispose()
