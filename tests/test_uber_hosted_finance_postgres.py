"""Real hosted-schema boot, durable exercise and restart in disposable PostgreSQL."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import DropSchema

from app.models.inventario import MovimientoInventario, Producto
from app.models.venta import Venta
from app.services import uber_finance_storage as storage
from app.services import uber_hosted_finance as finance
from app.services import uber_pos_sandbox_service as pos


def test_hosted_schema_is_durable_and_rejects_public_bind(monkeypatch):
    target = os.getenv("JACARANDA_TEST_POSTGRES_URL")
    if not target:
        pytest.skip("Explicit disposable PostgreSQL URL required")
    url = make_url(target)
    if url.host not in {"127.0.0.1", "localhost"} or url.database != "jacaranda_synthetic":
        pytest.fail("Only disposable local PostgreSQL is permitted")
    control = create_engine(url)
    assert not inspect(control).has_schema(storage.SCHEMA), "A fresh test schema is required; do not delete unknown data"
    monkeypatch.setattr(storage, "validate_configuration", lambda: url)
    monkeypatch.setenv("JACARANDA_RUNTIME", "uber-sandbox")
    from app.core.config import settings
    monkeypatch.setattr(settings, "UBER_EATS_SANDBOX_FINANCE_ENABLED", True)
    original_tables = set(inspect(control).get_table_names())
    try:
        storage.initialize()
        assert set(inspect(control).get_table_names()) == original_tables
        assert set(inspect(control).get_table_names(schema=storage.SCHEMA)) == storage.TABLES
        with Session(control) as db, pytest.raises(pos.RehearsalError):
            pos.validate_database(db)
        key = uuid4()
        with storage._sessions() as db:
            result = finance.exercise(db, key, True)
            assert result["completa"] and db.query(Venta).count() == 1
            assert db.query(MovimientoInventario).count() == 4
            assert [p.stock_actual for p in db.query(Producto).order_by(Producto.id)] == [98, 99]
        storage.shutdown()
        storage.initialize()
        with storage._sessions() as db:
            assert finance.exercise(db, key, True)["repetida"]
            assert [p.stock_actual for p in db.query(Producto).order_by(Producto.id)] == [98, 99]
            db.execute(text("SET search_path TO public"))
            with pytest.raises(pos.RehearsalError):
                pos.validate_database(db)
        assert set(inspect(control).get_table_names()) == original_tables
    finally:
        storage.shutdown()
        with control.begin() as connection:
            connection.execute(DropSchema(storage.SCHEMA, cascade=True))
        control.dispose()
