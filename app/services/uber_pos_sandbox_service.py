"""Local, disposable POS rehearsal. Never enabled in either deployed runtime."""

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.inventario import Ingrediente, Producto, TipoMovimiento, UnidadMedida
from app.models.usuario import RolUsuario, Usuario
from app.models.venta import (
    DetalleVenta, EstadoVenta, FormaPago, MetodoPago, PagoVenta, TerminalPago, Venta,
)
from app.schemas.inventario import MovimientoCreate
from app.services.auditoria_service import registrar_evento
from app.services.inventario_service import registrar_empaque_producto, registrar_movimiento
from app.services.venta_service import generar_ticket


TEST_CLIENT_ID = "I2pbZ-jD6Qa7FQzhLUbX3Y5gN12EasPL"
TEST_STORE_ID = "b412bb20-cf36-4ada-ba77-fdda96ce8a9e"
PROVIDER = "uber_eats_sandbox"
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999.99")


class RehearsalError(ValueError):
    """Reject an unsupported or unconfirmed case without making a sale."""


@dataclass(frozen=True)
class Money:
    net: Decimal
    tax: Decimal
    gross: Decimal


@dataclass(frozen=True)
class Line:
    item_id: str
    cart_item_id: str
    title: str
    quantity: int
    unit_net: Decimal
    discount_net: Decimal
    net: Decimal
    tax: Decimal
    gross: Decimal
    tax_rate: Decimal
    instructions: str


@dataclass(frozen=True)
class SalePlan:
    order_id: str
    state: str
    lines: tuple[Line, ...]
    total: Money
    instructions: str
    cash_due: Decimal | None


def _text(value, maximum=200) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RehearsalError("Identificador o texto de pedido no valido.")
    return value


def _instructions(value) -> str:
    if value is None:
        return ""
    return _text(value, 5000) if value != "" else ""


def _amount(value) -> Decimal:
    if not isinstance(value, dict) or value.get("currency_code") != "MXN":
        raise RehearsalError("Se requiere importe explicito en MXN.")
    raw = value.get("amount_e5")
    if type(raw) not in (int, float, Decimal):
        raise RehearsalError("Importe E5 no valido.")
    try:
        amount = Decimal(str(raw)) / Decimal(100000)
        if not amount.is_finite() or amount < 0 or amount > MAX_AMOUNT or amount != amount.quantize(CENT):
            raise RehearsalError("Importe negativo, fuera de rango o sin precision de centavos.")
    except InvalidOperation:
        raise RehearsalError("Importe E5 no valido.") from None
    return amount.quantize(CENT)


def _money(value, *, zero_tax=False) -> Money:
    if not isinstance(value, dict):
        raise RehearsalError("Falta desglose monetario del pedido.")
    gross = _amount(value.get("gross"))
    # The restaurant TEST API omits per-item net/tax on tax-free orders.
    # Only an explicit zero tax on the entire item summary permits this case.
    net = gross if zero_tax and "net" not in value else _amount(value.get("net"))
    tax = Decimal("0.00") if zero_tax and "tax" not in value else _amount(value.get("tax"))
    if net + tax != gross:
        raise RehearsalError("El desglose neto/impuesto/total no coincide.")
    return Money(net, tax, gross)


def _sum_money(values) -> Money:
    return Money(*(sum((getattr(value, key) for value in values), Decimal("0.00"))
                   for key in ("net", "tax", "gross")))


def _quantity(value) -> int:
    if (not isinstance(value, dict) or type(value.get("amount")) is not int
            or not 0 < value["amount"] <= 10000
            or value.get("unit", "PIECE") != "PIECE"
            or "in_sellable_unit" in value or "in_priceable_unit" in value):
        raise RehearsalError("El ensayo solo admite cantidades enteras por pieza.")
    return value["amount"]


def plan_order(payload: dict, *, client_id: str) -> SalePlan:
    """Normalize only the approved TEST store; no DB, network or price guessing."""
    if client_id != TEST_CLIENT_ID or not isinstance(payload, dict):
        raise RehearsalError("Solo se permite la aplicacion TEST aprobada.")
    order = payload.get("order")
    if (not isinstance(order, dict) or not isinstance(order.get("store"), dict)
            or order["store"].get("id") != TEST_STORE_ID):
        raise RehearsalError("Solo se permite la tienda Sandbox aprobada.")
    try:
        order_id = str(UUID(order.get("id")))
    except (ValueError, TypeError, AttributeError):
        raise RehearsalError("Pedido de pruebas no valido.") from None
    if order.get("state") not in {"ACCEPTED", "HANDED_OFF", "SUCCEEDED"}:
        raise RehearsalError("El pedido debe estar aceptado y no cancelado ni fallido.")
    try:
        payment = order["payment"]["payment_detail"]
        charges = payment["item_charges"]
        prices = charges["price_breakdown"]
    except (KeyError, TypeError):
        raise RehearsalError("Consulta el detalle completo con carts,payment.") from None
    if not isinstance(payment, dict) or not isinstance(charges, dict) or payment.get("currency_code") != "MXN":
        raise RehearsalError("Solo se permiten pedidos en MXN.")
    before = _money(charges.get("total"))
    total = _money(payment.get("order_total"))
    if total.gross <= 0:
        raise RehearsalError("El pedido debe tener un total positivo.")
    for key in ("fees", "tips", "adjustment"):
        if key in payment:
            if not isinstance(payment[key], dict) or _money(payment[key].get("total")).gross != 0:
                raise RehearsalError("Conciliar cargos, propinas o ajustes antes de importar.")
    cash_due = _money(payment["cash_amount_due"]).gross if "cash_amount_due" in payment else None
    if cash_due not in (None, Decimal("0.00")):
        raise RehearsalError("El ensayo no cobra efectivo ni importa pedidos con efectivo pendiente.")
    carts = order.get("carts")
    if not isinstance(carts, list) or not carts or len(carts) > 100 or not isinstance(prices, list) or len(prices) > 100:
        raise RehearsalError("Detalle de articulos incompleto o demasiado grande.")
    by_id = {}
    for price in prices:
        if not isinstance(price, dict) or price.get("price_type") != "ITEM":
            raise RehearsalError("Los modificadores requieren un mapeo y precio especificos.")
        cart_id = _text(price.get("cart_item_id"), 120)
        if cart_id in by_id:
            raise RehearsalError("Partida de precio duplicada.")
        by_id[cart_id] = price
    lines, originals, discounts, seen, instructions = [], [], [], set(), []
    if order.get("store_instructions"):
        instructions.append(_instructions(order["store_instructions"]))
    for cart in carts:
        if not isinstance(cart, dict) or not isinstance(cart.get("items"), list) or not cart["items"]:
            raise RehearsalError("Carrito sin articulos.")
        if cart.get("special_instructions"):
            instructions.append(_instructions(cart["special_instructions"]))
        for item in cart["items"]:
            if not isinstance(item, dict) or item.get("selected_modifier_groups") or item.get("fulfillment_action"):
                raise RehearsalError("Revisar modificadores o sustituciones antes de importar.")
            cart_id = _text(item.get("cart_item_id"), 120)
            if cart_id in seen or cart_id not in by_id:
                raise RehearsalError("Partida duplicada o sin precio explicito.")
            seen.add(cart_id)
            price = by_id[cart_id]
            quantity = _quantity(item.get("quantity"))
            if quantity != _quantity(price.get("quantity")):
                raise RehearsalError("La cantidad no coincide con el precio.")
            original = _money(price.get("total"), zero_tax=before.tax == 0)
            unit = _money(price.get("unit"), zero_tax=before.tax == 0)
            if original != Money(unit.net * quantity, unit.tax * quantity, unit.gross * quantity):
                raise RehearsalError("Precio unitario y total de partida no coinciden.")
            if "discount" in price and not isinstance(price["discount"], dict):
                raise RehearsalError("Descuento de partida no valido.")
            discount = _money(price["discount"].get("total"), zero_tax=before.tax == 0) if "discount" in price else Money(Decimal(0), Decimal(0), Decimal(0))
            net, tax, gross = original.net - discount.net, original.tax - discount.tax, original.gross - discount.gross
            if min(net, tax, gross) < 0 or (net == 0 and tax != 0):
                raise RehearsalError("Descuento o impuesto de partida no valido.")
            rate = (tax / net).quantize(Decimal("0.0001")) if net else Decimal(0)
            if rate > 1 or (net * rate).quantize(CENT) != tax:
                raise RehearsalError("Impuesto de partida no representable sin alterar importes.")
            request = item.get("customer_request", {})
            if not isinstance(request, dict):
                raise RehearsalError("Instrucciones de articulo no validas.")
            if set(request) - {"special_instructions", "allergy"}:
                raise RehearsalError("Las instrucciones incluyen campos que requieren revision.")
            notes = [_instructions(item.get("special_instructions")), _instructions(request.get("special_instructions")),
                     _instructions(request.get("allergy")), _instructions(item.get("allergy"))]
            lines.append(Line(_text(item.get("id"), 120), cart_id, _text(item.get("title")), quantity,
                              unit.net, discount.net, net, tax, gross, rate, "\n".join(note for note in notes if note)))
            originals.append(original)
            discounts.append(discount)
    if len(lines) > 100 or seen != set(by_id) or _sum_money(originals) != before:
        raise RehearsalError("Los articulos no concilian con el subtotal de Uber.")
    after = Money(sum((line.net for line in lines), Decimal(0)), sum((line.tax for line in lines), Decimal(0)),
                  sum((line.gross for line in lines), Decimal(0)))
    if after != total or ("subtotal_including_promos" in charges and _money(charges["subtotal_including_promos"]) != after):
        raise RehearsalError("El total requiere conciliar promociones o cargos no distribuidos.")
    if "promotions" in payment:
        if not isinstance(payment["promotions"], dict) or _money(payment["promotions"].get("total")) != _sum_money(discounts):
            raise RehearsalError("Las promociones no coinciden con los descuentos de las partidas.")
    return SalePlan(order_id, order["state"], tuple(lines), after, "\n".join(instructions), cash_due)


def validate_database(db: Session) -> None:
    """Allow no file DB, remote DB, alternate model bind, or deployed runtime."""
    if os.environ.get("JACARANDA_RUNTIME") != "uber-pos-rehearsal":
        raise RehearsalError("El enlace de ensayo no esta habilitado en servicios desplegados.")
    engine = db.get_bind().engine
    for mapper in Base.registry.mappers:
        if db.get_bind(mapper=mapper).engine is not engine:
            raise RehearsalError("Todos los modelos deben usar la misma base desechable.")
    url = engine.url
    if url.get_backend_name() == "sqlite" and url.database in (None, "", ":memory:"):
        return
    if (url.get_backend_name() == "postgresql" and url.host in {"127.0.0.1", "localhost"}
            and url.database == "jacaranda_synthetic"):
        with db.no_autoflush:
            schema = db.execute(func.current_schema().select()).scalar()
        if isinstance(schema, str) and schema.startswith("uber_pos_test_"):
            return
    raise RehearsalError("Solo se permite SQLite en memoria o PostgreSQL local desechable y aislado.")


def read_test_order(db: Session, order_id: UUID) -> tuple[dict, datetime]:
    """Read canonical TEST details only, after checking the local destination."""
    validate_database(db)
    from app.services import uber_order_service as orders

    if orders.sandbox_identity() != (TEST_CLIENT_ID, TEST_STORE_ID):
        raise RehearsalError("La consulta solo permite la identidad Sandbox aprobada.")
    observed = datetime.now(timezone.utc)
    payload = orders._request("GET", str(order_id), include_payment=True)
    if (not isinstance(payload.get("order"), dict) or payload["order"].get("id") != str(order_id)
            or not isinstance(payload["order"].get("store"), dict)
            or payload["order"]["store"].get("id") != TEST_STORE_ID):
        raise RehearsalError("Uber no confirmo el pedido solicitado.")
    return payload, observed


def import_order(db: Session, payload: dict, product_mapping: dict[str, int], usuario_id: int, *,
                 client_id: str, retrieved_at: datetime, reviewed: bool) -> dict:
    """Create one unliquidated test sale, stock movements and audit atomically."""
    validate_database(db)
    if reviewed is not True:
        raise RehearsalError("Revisa productos e instrucciones antes de registrar el ensayo.")
    if db.new or db.dirty or db.deleted:
        raise RehearsalError("Usa una sesion sin cambios pendientes para el ensayo.")
    plan = plan_order(payload, client_id=client_id)
    if not isinstance(product_mapping, dict) or any(
        type(product_mapping.get(line.item_id)) is not int or product_mapping[line.item_id] <= 0 for line in plan.lines
    ):
        raise RehearsalError("Falta el mapeo explicito de un articulo al catalogo de ensayo.")
    normalized = {"order_id": plan.order_id, "client_id": client_id, "store_id": TEST_STORE_ID,
                  "lines": [asdict(line) | {"product_id": product_mapping[line.item_id]} for line in plan.lines],
                  "total": asdict(plan.total), "instructions": plan.instructions, "cash_due": plan.cash_due}
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
    fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
    identity = hashlib.sha256(f"{client_id}:{TEST_STORE_ID}:{plan.order_id}".encode()).hexdigest()
    key = "uber-sandbox:" + identity
    try:
        connection = db.connection()
        if connection.dialect.name == "postgresql":
            db.execute(func.pg_advisory_xact_lock(211025, 1).select())
        elif not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        operator = db.get(Usuario, usuario_id)
        if not operator or not operator.activo or operator.rol != RolUsuario.ADMINISTRADOR:
            raise RehearsalError("Se requiere un operador administrador de ensayo activo.")
        existing = db.query(Venta).filter_by(idempotency_key=key).populate_existing().first()
        if existing:
            saved = json.loads(existing.pago_externo_payload or "{}")
            if existing.pago_proveedor != PROVIDER or saved.get("fingerprint") != fingerprint:
                raise RehearsalError("El pedido ya tiene otros importes, instrucciones o mapeo; requiere revision.")
            db.commit()
            return {"venta_id": existing.id, "folio": existing.folio, "repetida": True}
        if (not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None
                or not 0 <= (datetime.now(timezone.utc) - retrieved_at).total_seconds() <= 120):
            raise RehearsalError("Consulta un detalle de pruebas reciente antes de importar.")
        with db.begin_nested():
            quantities = {}
            for line in plan.lines:
                product_id = product_mapping[line.item_id]
                quantities[product_id] = quantities.get(product_id, 0) + line.quantity
            products = {product.id: product for product in db.query(Producto).filter(
                Producto.id.in_(quantities),
            ).order_by(Producto.id).populate_existing().with_for_update().all()}
            if set(products) != set(quantities) or any(
                not product.activo or product.unidad_medida != UnidadMedida.PIEZA
                or product.stock_actual < quantities[product.id] for product in products.values()
            ):
                raise RehearsalError("Producto no disponible o stock insuficiente para el ensayo.")
            sale = Venta(folio="US-" + identity[:24], serie="US", idempotency_key=key, canal="uber_eats",
                         usuario_id=usuario_id, subtotal=plan.total.net,
                         descuento=sum((line.discount_net for line in plan.lines), Decimal(0)),
                         iva_0=sum((line.net for line in plan.lines if line.tax == 0), Decimal(0)),
                         iva_16=plan.total.tax, total_impuestos=plan.total.tax, total=plan.total.gross,
                         metodo_pago=MetodoPago.POR_DEFINIR, forma_pago=FormaPago.PPD,
                         terminal=TerminalPago.EFECTIVO, monto_recibido=Decimal(0), cambio=Decimal(0),
                         estado=EstadoVenta.PENDIENTE, pago_integrado=False, pago_proveedor=PROVIDER,
                         pago_externo_id=plan.order_id, pago_externo_estado="ensayo_por_conciliar",
                         pago_externo_payload=json.dumps({"fingerprint": fingerprint, "order": normalized,
                                                          "observed_state": plan.state, "retrieved_at": retrieved_at.isoformat()}, default=str),
                         notas="ENSAYO UBER_TEST. Sin cobro ni liquidacion real.\n" + plan.instructions)
            db.add(sale)
            db.flush()
            for line in plan.lines:
                product = products[product_mapping[line.item_id]]
                db.add(DetalleVenta(venta_id=sale.id, producto_id=product.id, cantidad=line.quantity,
                                    precio_unitario=line.unit_net, descuento=line.discount_net, subtotal=line.net,
                                    clave_prod_serv_sat=product.clave_prod_serv_sat, clave_unidad_sat=product.clave_unidad_sat,
                                    tasa_iva=line.tax_rate, monto_iva=line.tax, objeto_impuesto=product.objeto_impuesto))
            db.add(PagoVenta(venta_id=sale.id, metodo_pago=MetodoPago.POR_DEFINIR, terminal=None,
                             proveedor=PROVIDER, estado="por_conciliar", pago_externo_id=plan.order_id,
                             monto=plan.total.gross, referencia="ENSAYO UBER_TEST. Sin cobro real."))
            # Lock shared packaging in a stable order before the existing stock helpers.
            box_ids = sorted({product.caja_ingrediente_id for product in products.values() if product.caja_ingrediente_id})
            if box_ids:
                db.query(Ingrediente).filter(Ingrediente.id.in_(box_ids)).order_by(Ingrediente.id).with_for_update().all()
            for product_id, quantity in sorted(quantities.items()):
                registrar_movimiento(db, MovimientoCreate(producto_id=product_id, tipo=TipoMovimiento.SALIDA_VENTA,
                                                          cantidad=quantity, referencia="Ensayo " + sale.folio),
                                     usuario_id, commit=False)
                registrar_empaque_producto(db, products[product_id], Decimal(quantity), "Ensayo " + sale.folio,
                                           usuario_id, commit=False, permitir_stock_negativo=False)
            registrar_evento(db, usuario_id, operator.nombre, "importar_uber_sandbox", "ventas", "ventas", sale.id,
                              datos_nuevos={"pedido_id": plan.order_id, "folio": sale.folio, "fingerprint": fingerprint,
                                            "total": str(plan.total.gross), "estado": "pendiente", "ensayo": True}, commit=False)
        db.commit()
        return {"venta_id": sale.id, "folio": sale.folio, "repetida": False}
    except Exception:
        db.rollback()
        raise


def rehearsal_ticket(db: Session, venta_id: int) -> dict:
    validate_database(db)
    sale = db.get(Venta, venta_id)
    if not sale or sale.pago_proveedor != PROVIDER or sale.estado != EstadoVenta.PENDIENTE:
        raise RehearsalError("Venta de ensayo pendiente no encontrada.")
    ticket = generar_ticket(db, venta_id)
    saved = json.loads(sale.pago_externo_payload)
    ticket.update(razon_social="Jacaranda Sandbox - ENSAYO", rfc="NO APLICA - ENSAYO",
                  metodo_pago="Uber TEST - pago y liquidacion no conciliados",
                  leyenda_fiscal="ENSAYO. Sin cobro real. No es factura ni comprobante de pago.",
                  instrucciones=saved["order"]["instructions"],
                  instrucciones_articulos=[line["instructions"] for line in saved["order"]["lines"]])
    return ticket
