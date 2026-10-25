"""Explicit financial TEST operations. All outgoing Uber calls are canonical GETs."""

import copy
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL

from sqlalchemy.orm import Session

from app.models.inventario import Ingrediente, MovimientoInventario, Producto
from app.models.uber_eats import UberSandboxAction, UberSandboxEvent
from app.models.venta import Venta
from app.services import uber_finance_storage as storage
from app.services import uber_order_service as orders
from app.services import uber_pos_reconciliation as reconcile
from app.services import uber_pos_sandbox_service as pos


CHANGES = {"orders.cancel", "orders.failure", "orders.customer_order_edit",
           "orders.fulfillment_issues.resolved", "order.fulfillment_issues.resolved"}


def events(db: Session, order_id: str):
    return db.query(UberSandboxEvent).filter_by(client_id=pos.TEST_CLIENT_ID, store_id=pos.TEST_STORE_ID,
                                               order_id=order_id).order_by(UberSandboxEvent.id).all()


def sale_for(db: Session, order_id: str):
    return db.query(Venta).filter_by(canal="uber_eats", pago_proveedor=pos.PROVIDER, pago_externo_id=order_id).first()


def pending_action(db: Session, order_id: str):
    return db.query(UberSandboxAction.id).filter_by(client_id=pos.TEST_CLIENT_ID, store_id=pos.TEST_STORE_ID,
                                                   order_id=order_id).filter(
        UberSandboxAction.estado.in_(("enviando", "incierta")),
    ).first() is not None


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def event_warning(sale: Venta, rows) -> list[str]:
    saved = json.loads(sale.pago_externo_payload)
    seen = datetime.fromisoformat(saved.get("lifecycle", {}).get("observed_at", saved["retrieved_at"]))
    if any(row.event_type in {"orders.cancel", "orders.failure"} for row in rows):
        return ["cancelacion_por_revisar"]
    if any(row.event_type in CHANGES and _utc(row.recibido_en) >= seen for row in rows):
        return ["aviso_nuevo_por_revisar"]
    return []


def inspect_order(public: Session, db: Session, order_id: str):
    pos.validate_database(db)
    order_id = str(UUID(order_id))
    rows = events(public, order_id)
    if not rows:
        raise pos.RehearsalError("Falta una notificacion autentica de la tienda TEST para este pedido.")
    if pending_action(public, order_id):
        raise pos.RehearsalError("Primero verifica la accion de Uber pendiente de confirmar.")
    observed = datetime.now(timezone.utc)
    payload = orders._request("GET", order_id, include_payment=True)
    order = payload.get("order") if isinstance(payload, dict) else None
    if (not isinstance(order, dict) or order.get("id") != order_id or not isinstance(order.get("store"), dict)
            or order["store"].get("id") != pos.TEST_STORE_ID or not isinstance(order.get("state"), str)
            or order["state"] not in reconcile.RANK):
        raise pos.RehearsalError("Se requiere un pedido TEST aceptado, entregado o fallido con identidad confirmada.")
    public.expire_all()
    rows = events(public, order_id)
    canceled = any(row.event_type in {"orders.cancel", "orders.failure"} for row in rows)
    plan, problem = None, None
    try:
        plan = pos.plan_order(payload, client_id=pos.TEST_CLIENT_ID)
    except pos.RehearsalError as exc:
        problem = str(exc)
    # The digest includes fresh signed events; a changed preview cannot be submitted.
    evidence = {"order_id": order_id, "state": order["state"], "plan": asdict(plan) if plan else None,
                "problem": problem, "event_ids": [row.id for row in rows]}
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
    sale = sale_for(db, order_id)
    return {"pedido_id": order_id, "estado": order["state"], "detalle_sha256": digest,
            "consultado_en": observed.isoformat(), "plan": asdict(plan) if plan else None,
            "problema": problem, "cancelacion": canceled, "registrable": plan is not None and not canceled,
            "venta_id": sale.id if sale else None, "revision": sale.edicion_revision if sale else 0}, payload, observed


def perform(public: Session, db: Session, order_id: str, *, action: str, digest: str, revision: int,
            reviewed: bool, reference: str | None = None, gross: str | None = None,
            deductions: str | None = None, net: str | None = None):
    if action not in {"registrar", "actualizar", "conciliar"}:
        raise pos.RehearsalError("Operacion financiera no permitida.")
    if reviewed is not True:
        raise pos.RehearsalError("Confirma la revision del pedido y que es solo Sandbox.")
    current, payload, observed = inspect_order(public, db, order_id)
    if current["detalle_sha256"] != digest:
        raise pos.RehearsalError("El detalle o los avisos cambiaron. Actualiza y revisa antes de confirmar.")
    operator, mapping = storage.bindings(db)
    if action == "registrar":
        if not current["registrable"]:
            raise pos.RehearsalError("No se registra un pedido cancelado, fallido o con importes no conciliables.")
        return pos.import_order(db, payload, mapping, operator, client_id=pos.TEST_CLIENT_ID,
                                retrieved_at=observed, reviewed=True)
    sale = sale_for(db, order_id)
    if sale is None:
        raise pos.RehearsalError("Primero registra el pedido en ventas TEST.")
    saved = json.loads(sale.pago_externo_payload)
    if action == "conciliar" and saved.get("settlement") and not current["cancelacion"]:
        # A repeated allocation still requires the same canonical financial evidence.
        if current["estado"] != "SUCCEEDED" or current["plan"] is None:
            raise pos.RehearsalError("La entrega requiere otra revision.")
        original = saved["order"]
        details = current["plan"]
        expected = {"lines": [{k: v for k, v in line.items() if k != "product_id"} for line in original["lines"]],
                    **{k: original[k] for k in ("total", "instructions", "cash_due")}}
        actual = {k: details[k] for k in expected}
        if json.dumps(actual, sort_keys=True, default=str) != json.dumps(expected, sort_keys=True, default=str):
            raise pos.RehearsalError("El pedido cambio despues de la liquidacion ficticia; registra la revision.")
        return reconcile.record_test_settlement(db, sale.id, operator, reference=reference, gross=gross,
            deductions=deductions, net=net, expected_revision=revision, reviewed=True)
    result = reconcile.observe_order(db, sale.id, payload, operator, client_id=pos.TEST_CLIENT_ID,
        retrieved_at=observed, expected_revision=revision, reviewed=True, cancellation_seen=current["cancelacion"])
    if action == "actualizar":
        return result
    return reconcile.record_test_settlement(db, sale.id, operator, reference=reference, gross=gross,
        deductions=deductions, net=net, expected_revision=result["revision"], reviewed=True)


def report(public: Session, db: Session):
    data = reconcile.external_report(db)
    totals = {key: Decimal(value) for key, value in data["totales"].items()}
    for row in data["pedidos"]:
        sale = db.get(Venta, row["venta_id"])
        notices = events(public, row["pedido_id"])
        row["fuente"] = "Uber TEST" if notices else "Simulacion interna"
        warnings = event_warning(sale, notices)
        if pending_action(public, row["pedido_id"]):
            warnings.append("accion_uber_por_confirmar")
        if warnings:
            if row["estado"] != "revision_pendiente":
                key = "bruto_conciliado_test" if row["estado"] == "conciliado_test" else "bruto_por_conciliar"
                totals[key] -= sale.total
                totals["bruto_en_revision"] += sale.total
                if row["estado"] == "conciliado_test":
                    totals["deducciones_test"] -= Decimal(row["liquidacion_ficticia"]["deductions"])
                    totals["neto_test"] -= Decimal(row["liquidacion_ficticia"]["net"])
            row["estado"] = "revision_pendiente"
            row["motivos"] = sorted(set(row["motivos"] + warnings))
    data["totales"] = {key: str(value) for key, value in totals.items()}
    data["inventario"] = [{"codigo": item.codigo, "producto": item.nombre, "existencias": str(item.stock_actual)}
                           for item in db.query(Producto).order_by(Producto.id)]
    data["empaques"] = [{"producto": item.nombre, "existencias": str(item.stock_actual)}
                        for item in db.query(Ingrediente).filter_by(es_empaque=True)]
    data["movimientos"] = db.query(MovimientoInventario).count()
    return data


def ticket(public: Session, db: Session, sale_id: int):
    pos.validate_database(db)
    sale = db.get(Venta, sale_id)
    if (not sale or pending_action(public, sale.pago_externo_id)
            or event_warning(sale, events(public, sale.pago_externo_id))):
        raise pos.RehearsalError("El pedido no existe o tiene avisos por revisar.")
    return pos.rehearsal_ticket(db, sale_id)


def exercise(db: Session, request_key: UUID, reviewed: bool):
    """Persist an explicitly synthetic end-to-end exercise, with no Uber requests."""
    pos.validate_database(db)
    if reviewed is not True:
        raise pos.RehearsalError("Confirma que el ensayo es ficticio y no tiene cobros.")
    order_id = str(uuid5(NAMESPACE_URL, "jacaranda-finance-test:" + str(request_key)))
    existing = sale_for(db, order_id)
    if existing:
        return {"venta_id": existing.id, "repetida": True, "fuente": "synthetic_fixture", "completa": bool(
            json.loads(existing.pago_externo_payload).get("lifecycle", {}).get("cancellation_seen"))}
    payload = json.loads((Path(__file__).resolve().parents[2] / "scripts/fixtures/uber_pos_order.json").read_text())
    payload["order"]["id"] = order_id
    for cart in payload["order"]["carts"]:
        for item in cart["items"]:
            if item["id"] == "jacaranda-sandbox-cookie":
                item["id"] = "jacaranda-sandbox-galleta"
    operator, mapping = storage.bindings(db)
    first = pos.import_order(db, payload, mapping, operator, client_id=pos.TEST_CLIENT_ID,
                             retrieved_at=datetime.now(timezone.utc), reviewed=True)
    sale_id = first["venta_id"]
    delivered = copy.deepcopy(payload)
    delivered["order"]["state"] = "SUCCEEDED"
    reconcile.observe_order(db, sale_id, delivered, operator, client_id=pos.TEST_CLIENT_ID,
        retrieved_at=datetime.now(timezone.utc), expected_revision=0, reviewed=True)
    reconcile.record_test_settlement(db, sale_id, operator, reference="TEST-" + str(request_key),
        gross="4.00", deductions="1.00", net="3.00", expected_revision=1, reviewed=True)
    reconcile.observe_order(db, sale_id, delivered, operator, client_id=pos.TEST_CLIENT_ID,
        retrieved_at=datetime.now(timezone.utc), expected_revision=2, reviewed=True, cancellation_seen=True)
    return {"venta_id": sale_id, "repetida": False, "fuente": "synthetic_fixture", "completa": True,
            "bruto": "4.00", "deducciones": "1.00", "neto": "3.00", "cobros_reales": 0,
            "cancelacion_por_revisar": True}
