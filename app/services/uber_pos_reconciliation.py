"""Order lifecycle and fictional settlements in the disposable POS rehearsal only."""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.usuario import RolUsuario, Usuario
from app.models.venta import EstadoVenta, PagoVenta, Venta
from app.services import uber_pos_sandbox_service as pos
from app.services.auditoria_service import registrar_evento


RANK = {"ACCEPTED": 1, "HANDED_OFF": 2, "SUCCEEDED": 3, "FAILED": 3}


def _encoded(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value) -> str:
    return hashlib.sha256(_encoded(value).encode()).hexdigest()


def _instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise pos.RehearsalError("La consulta requiere fecha y zona horaria explicitas.")
    return value.astimezone(timezone.utc)


def _fresh(value: datetime) -> datetime:
    value = _instant(value)
    if not 0 <= (datetime.now(timezone.utc) - value).total_seconds() <= 120:
        raise pos.RehearsalError("Consulta un detalle reciente antes de revisar el ensayo.")
    return value


@contextmanager
def _locked_sale(db: Session, sale_id: int, operator_id: int):
    pos.validate_database(db)
    if db.new or db.dirty or db.deleted:
        raise pos.RehearsalError("Usa una sesion sin cambios pendientes para el ensayo.")
    try:
        connection = db.connection()
        if connection.dialect.name == "postgresql":
            db.execute(func.pg_advisory_xact_lock(211025, 1).select())
        elif not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        operator = db.get(Usuario, operator_id, populate_existing=True)
        if not operator or not operator.activo or operator.rol != RolUsuario.ADMINISTRADOR:
            raise pos.RehearsalError("Se requiere un operador administrador de ensayo activo.")
        sale = db.query(Venta).filter_by(id=sale_id, pago_proveedor=pos.PROVIDER, canal="uber_eats").populate_existing().with_for_update().first()
        if not sale or sale.estado != EstadoVenta.PENDIENTE or sale.monto_recibido != 0 or sale.facturada:
            raise pos.RehearsalError("Se requiere una venta pendiente de ensayo, sin cobro ni factura.")
        payments = db.query(PagoVenta).filter_by(venta_id=sale.id).populate_existing().all()
        if (len(payments) != 1 or payments[0].proveedor != pos.PROVIDER
                or payments[0].pago_externo_id != sale.pago_externo_id or payments[0].monto != sale.total):
            raise pos.RehearsalError("El pago informativo de ensayo requiere revision.")
        saved = json.loads(sale.pago_externo_payload or "{}")
        if saved.get("order", {}).get("client_id") != pos.TEST_CLIENT_ID or saved["order"].get("store_id") != pos.TEST_STORE_ID:
            raise pos.RehearsalError("La venta no corresponde a la identidad Sandbox aprobada.")
        yield sale, payments[0], saved, operator
        db.commit()
    except Exception:
        db.rollback()
        raise


def _revision(sale: Venta, expected: int):
    if type(expected) is not int or expected != sale.edicion_revision:
        raise pos.RehearsalError("La revision cambio; vuelve a consultar antes de confirmar.")


def _result(sale: Venta, saved: dict, repeated: bool) -> dict:
    return {"venta_id": sale.id, "revision": sale.edicion_revision, "repetida": repeated,
            "requiere_revision": bool(saved.get("lifecycle", {}).get("reasons")),
            "estado_externo": sale.pago_externo_estado, "efectivo_recibido": "0.00", "ensayo": True}


def observe_order(db: Session, sale_id: int, payload: dict, operator_id: int, *,
                  client_id: str, retrieved_at: datetime, expected_revision: int,
                  reviewed: bool, cancellation_seen: bool = False) -> dict:
    """Record fresh TEST evidence, never overwrite amounts or reverse stock."""
    pos.validate_database(db)
    if reviewed is not True or type(cancellation_seen) is not bool:
        raise pos.RehearsalError("Revisa el detalle y la notificacion antes de registrar el ensayo.")
    observed = _instant(retrieved_at)
    order = payload.get("order") if isinstance(payload, dict) else None
    if (client_id != pos.TEST_CLIENT_ID or not isinstance(order, dict)
            or not isinstance(order.get("store"), dict) or order["store"].get("id") != pos.TEST_STORE_ID
            or not isinstance(order.get("state"), str) or order["state"] not in RANK):
        raise pos.RehearsalError("La consulta debe corresponder a un pedido de la tienda TEST aprobada.")
    try:
        order_id = str(UUID(order.get("id")))
    except (ValueError, TypeError, AttributeError):
        raise pos.RehearsalError("Identidad de pedido no valida.") from None
    with _locked_sale(db, sale_id, operator_id) as (sale, payment, saved, operator):
        if order_id != sale.pago_externo_id:
            raise pos.RehearsalError("La consulta no corresponde a esta venta de ensayo.")
        previous = saved.get("lifecycle", {})
        previous_time = _instant(datetime.fromisoformat(previous.get("observed_at", saved["retrieved_at"])))
        reasons = set(previous.get("reasons", []))
        previous_state = previous.get("state", saved["observed_state"])
        state = order["state"]
        if RANK[state] < RANK[previous_state] or (previous_state in {"FAILED", "SUCCEEDED"} and state != previous_state):
            reasons.add("estado_remoto_en_conflicto")
        if cancellation_seen or previous.get("cancellation_seen"):
            reasons.add("cancelacion_por_revisar")
        if state == "FAILED":
            reasons.add("pedido_fallido_sin_reponer_stock")
        details = None
        if state != "FAILED":
            try:
                plan = pos.plan_order(payload, client_id=client_id)
                details = {"lines": [asdict(line) for line in plan.lines], "total": asdict(plan.total),
                           "instructions": plan.instructions, "cash_due": plan.cash_due}
                original = saved["order"]
                expected = {"lines": [{k: v for k, v in line.items() if k != "product_id"} for line in original["lines"]],
                            **{k: original[k] for k in ("total", "instructions", "cash_due")}}
                if _encoded(details) != _encoded(expected):
                    reasons.add("detalle_cambiado")
            except pos.RehearsalError:
                reasons.add("detalle_no_conciliable")
        evidence = {"state": state, "observed_at": observed.isoformat(), "cancellation_seen": cancellation_seen,
                    "details": details}
        digest = _fingerprint(evidence)
        if previous.get("fingerprint") == digest:
            return _result(sale, saved, True)
        _revision(sale, expected_revision)
        _fresh(observed)
        if observed <= previous_time:
            raise pos.RehearsalError("La consulta es anterior a la ultima evidencia; vuelve a consultar.")
        saved["lifecycle"] = {"state": previous_state if "estado_remoto_en_conflicto" in reasons else state,
                              "remote_state": state, "observed_at": observed.isoformat(),
                              "cancellation_seen": cancellation_seen or previous.get("cancellation_seen", False),
                              "reasons": sorted(reasons), "fingerprint": digest}
        sale.edicion_revision += 1
        sale.pago_externo_estado = ("ensayo_revision_pendiente" if reasons else
                                   "ensayo_conciliado" if saved.get("settlement") else
                                   "ensayo_entregado_por_conciliar" if state == "SUCCEEDED" else "ensayo_por_conciliar")
        payment.estado = "revision_pendiente" if reasons else payment.estado
        sale.pago_externo_payload = _encoded(saved)
        registrar_evento(db, operator.id, operator.nombre, "revisar_uber_sandbox", "ventas", "ventas", sale.id,
                          datos_nuevos={"ensayo": True, "estado": state, "revision": sale.edicion_revision,
                                        "motivos": sorted(reasons), "stock_modificado": False}, commit=False)
        return _result(sale, saved, False)


def _pesos(value) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise pos.RehearsalError("Los importes del ensayo deben ser decimales exactos en MXN.")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0 or amount > pos.MAX_AMOUNT or amount != amount.quantize(pos.CENT):
            raise InvalidOperation
        return amount.quantize(pos.CENT)
    except (InvalidOperation, ValueError):
        raise pos.RehearsalError("Importe de liquidacion ficticia no valido.") from None


def record_test_settlement(db: Session, sale_id: int, operator_id: int, *, reference: str,
                           gross: str, deductions: str, net: str, expected_revision: int,
                           reviewed: bool) -> dict:
    """Explicit fictional per-order allocation, not a charge or bank deposit."""
    pos.validate_database(db)
    if reviewed is not True:
        raise pos.RehearsalError("Confirma la revision de la liquidacion ficticia.")
    if not isinstance(reference, str) or not reference.startswith("TEST-") or not 6 <= len(reference) <= 100:
        raise pos.RehearsalError("La referencia ficticia debe comenzar con TEST-.")
    gross, deductions, net = (_pesos(value) for value in (gross, deductions, net))
    if gross <= 0 or deductions > gross or gross - deductions != net:
        raise pos.RehearsalError("Bruto menos deducciones debe coincidir exactamente con neto.")
    values = {"reference": reference, "gross": str(gross), "deductions": str(deductions), "net": str(net), "synthetic": True}
    with _locked_sale(db, sale_id, operator_id) as (sale, payment, saved, operator):
        if gross != sale.total:
            raise pos.RehearsalError("El bruto de la liquidacion no coincide con el pedido.")
        lifecycle = saved.get("lifecycle", {})
        if lifecycle.get("state") != "SUCCEEDED" or lifecycle.get("reasons"):
            raise pos.RehearsalError("Falta entrega confirmada sin cambios ni cancelaciones por revisar.")
        previous = saved.get("settlement")
        if previous:
            if previous != values:
                raise pos.RehearsalError("La liquidacion ya tiene otros datos; no se sobrescribe.")
            return _result(sale, saved, True)
        _revision(sale, expected_revision)
        _fresh(datetime.fromisoformat(lifecycle["observed_at"]))
        if db.query(Venta.id).filter_by(pago_proveedor=pos.PROVIDER, pago_externo_referencia=reference).first():
            raise pos.RehearsalError("La referencia ya pertenece a otro pedido de ensayo.")
        saved["settlement"] = values
        sale.edicion_revision += 1
        sale.pago_externo_referencia = reference
        sale.pago_externo_estado = "ensayo_conciliado"
        sale.pago_externo_payload = _encoded(saved)
        payment.estado = "conciliado_test"
        # Keep sale pending, received cash zero and the gross informational payment.
        registrar_evento(db, operator.id, operator.nombre, "conciliar_uber_sandbox", "ventas", "ventas", sale.id,
                          datos_nuevos={**values, "ensayo": True, "revision": sale.edicion_revision}, commit=False)
        return _result(sale, saved, False)


def external_report(db: Session) -> dict:
    """Read-only test channel totals, explicitly separate from the cashier cut."""
    pos.validate_database(db)
    if db.new or db.dirty or db.deleted:
        raise pos.RehearsalError("Usa una sesion sin cambios pendientes para el ensayo.")
    totals = {key: Decimal("0.00") for key in ("bruto_pedidos", "bruto_por_conciliar", "bruto_en_revision",
                                             "bruto_conciliado_test", "deducciones_test", "neto_test")}
    entries = []
    for sale in db.query(Venta).filter_by(pago_proveedor=pos.PROVIDER, canal="uber_eats").order_by(Venta.id):
        if sale.estado != EstadoVenta.PENDIENTE or sale.monto_recibido != 0 or sale.facturada:
            raise pos.RehearsalError("El ensayo contiene una venta fuera del estado aislado esperado.")
        saved = json.loads(sale.pago_externo_payload)
        lifecycle, settlement = saved.get("lifecycle", {}), saved.get("settlement")
        reasons = lifecycle.get("reasons", [])
        status = "revision_pendiente" if reasons else "conciliado_test" if settlement else "por_conciliar"
        totals["bruto_pedidos"] += sale.total
        totals[{"revision_pendiente": "bruto_en_revision", "conciliado_test": "bruto_conciliado_test",
                "por_conciliar": "bruto_por_conciliar"}[status]] += sale.total
        if settlement and not reasons:
            totals["deducciones_test"] += Decimal(settlement["deductions"])
            totals["neto_test"] += Decimal(settlement["net"])
        entries.append({"venta_id": sale.id, "pedido_id": sale.pago_externo_id, "revision": sale.edicion_revision,
                        "estado": status, "motivos": reasons, "bruto": str(sale.total),
                        "liquidacion_ficticia": settlement})
    return {"ensayo": True, "moneda": "MXN", "efectivo_caja": "0.00",
            "totales": {key: str(value) for key, value in totals.items()}, "pedidos": entries}
