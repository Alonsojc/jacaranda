"""Native transaction races in a separate, disposable local PostgreSQL schema."""

import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.core.database import Base
from app.models.inventario import Ingrediente, MovimientoInventario, Producto, UnidadMedida
from app.models.usuario import RolUsuario, Usuario
from app.models.venta import PagoVenta, Venta
from app.services import uber_pos_sandbox_service as pos


@pytest.fixture
def pos_pg(monkeypatch):
    target = os.getenv("JACARANDA_TEST_POSTGRES_URL")
    if not target:
        pytest.skip("Explicit disposable PostgreSQL URL required")
    url = make_url(target)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "jacaranda_synthetic":
        pytest.fail("Only a local disposable jacaranda_synthetic PostgreSQL is permitted")
    schema = "uber_pos_test_" + uuid4().hex
    control = create_engine(url)
    with control.begin() as connection:
        connection.execute(CreateSchema(schema))
    engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
    monkeypatch.setenv("JACARANDA_RUNTIME", "uber-pos-rehearsal")
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            pos.validate_database(db)
        Base.metadata.create_all(engine)
        with sessions() as db:
            user = Usuario(nombre="Fictional operator", email="uber-test@example.invalid",
                           hashed_password="not-a-login-credential", rol=RolUsuario.ADMINISTRADOR)
            box = Ingrediente(nombre="Fictional box", unidad_medida=UnidadMedida.CAJA,
                              es_empaque=True, stock_actual=Decimal(20), costo_unitario=Decimal(1))
            db.add_all([user, box])
            db.flush()
            products = [Producto(codigo="FICTITIOUS-" + str(index), nombre=name, precio_unitario=Decimal(99),
                                 stock_actual=Decimal(10), caja_ingrediente_id=box.id, caja_cantidad=Decimal(1))
                        for index, name in enumerate(("Fictional brownie", "Fictional cookie"))]
            db.add_all(products)
            db.commit()
            mapping = {"jacaranda-sandbox-brownie": products[0].id, "jacaranda-sandbox-cookie": products[1].id}
            user_id = user.id
        payload = json.loads((Path(__file__).parents[1] / "scripts/fixtures/uber_pos_order.json").read_text())
        yield sessions, payload, mapping, user_id
    finally:
        engine.dispose()
        with control.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        control.dispose()


def run_simultaneous(sessions, payloads, mapping, user_id):
    barrier = Barrier(len(payloads))

    def invoke(payload):
        with sessions() as db:
            barrier.wait(timeout=15)
            try:
                return pos.import_order(db, payload, mapping, user_id, client_id=pos.TEST_CLIENT_ID,
                                        retrieved_at=datetime.now(timezone.utc), reviewed=True)
            except pos.RehearsalError:
                return {"blocked": True}

    with ThreadPoolExecutor(max_workers=len(payloads)) as workers:
        return list(workers.map(invoke, payloads))


def test_concurrent_duplicate_creates_one_sale_and_one_stock_effect(pos_pg):
    sessions, payload, mapping, user_id = pos_pg
    results = run_simultaneous(sessions, [payload, copy.deepcopy(payload)], mapping, user_id)
    assert sorted(result["repetida"] for result in results) == [False, True]
    assert results[0]["venta_id"] == results[1]["venta_id"]
    with sessions() as db:
        assert db.query(Venta).count() == 1 and db.query(PagoVenta).count() == 1
        assert db.query(MovimientoInventario).count() == 4
        assert [db.get(Producto, product_id).stock_actual for product_id in mapping.values()] == [8, 9]
        assert db.query(Ingrediente).one().stock_actual == 17


def test_different_orders_preserve_combined_inventory_under_concurrency(pos_pg):
    sessions, payload, mapping, user_id = pos_pg
    other = copy.deepcopy(payload)
    other["order"]["id"] = str(uuid4())
    results = run_simultaneous(sessions, [payload, other], mapping, user_id)
    assert all(result["repetida"] is False for result in results)
    with sessions() as db:
        assert db.query(Venta).count() == 2 and db.query(MovimientoInventario).count() == 8
        assert [db.get(Producto, product_id).stock_actual for product_id in mapping.values()] == [6, 8]
        assert db.query(Ingrediente).one().stock_actual == 14


def test_concurrent_orders_cannot_oversell_last_units(pos_pg):
    sessions, payload, mapping, user_id = pos_pg
    with sessions() as db:
        db.get(Producto, mapping["jacaranda-sandbox-brownie"]).stock_actual = 2
        db.commit()
    other = copy.deepcopy(payload)
    other["order"]["id"] = str(uuid4())
    results = run_simultaneous(sessions, [payload, other], mapping, user_id)
    assert sum(result.get("blocked", False) for result in results) == 1
    with sessions() as db:
        assert db.query(Venta).count() == 1 and db.query(MovimientoInventario).count() == 4
        assert db.get(Producto, mapping["jacaranda-sandbox-brownie"]).stock_actual == 0
        assert db.query(Ingrediente).one().stock_actual == 17


def test_postgres_failure_after_stock_write_rolls_back_sale_payment_and_stock(pos_pg):
    sessions, payload, mapping, user_id = pos_pg
    with sessions() as db, patch.object(pos, "registrar_empaque_producto", side_effect=RuntimeError("synthetic")):
        with pytest.raises(RuntimeError):
            pos.import_order(db, payload, mapping, user_id, client_id=pos.TEST_CLIENT_ID,
                             retrieved_at=datetime.now(timezone.utc), reviewed=True)
    with sessions() as db:
        assert db.query(Venta).count() == 0 and db.query(PagoVenta).count() == 0
        assert db.query(MovimientoInventario).count() == 0
        assert [db.get(Producto, product_id).stock_actual for product_id in mapping.values()] == [10, 10]
