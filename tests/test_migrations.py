"""Regression tests for Alembic bootstrap migrations."""

import os
import subprocess
import sys
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_HEAD = "83d9a71bc502 (head)"


def _run(command: list[str], database_url: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_alembic_upgrade_head_on_clean_database(tmp_path):
    db_path = tmp_path / "clean.db"
    database_url = f"sqlite:///{db_path}"

    _run([sys.executable, "-m", "alembic", "upgrade", "head"], database_url)
    current = _run([sys.executable, "-m", "alembic", "current"], database_url)

    assert ALEMBIC_HEAD in current.stdout

    conn = sqlite3.connect(db_path)
    try:
        producto_columns = {row[1] for row in conn.execute("PRAGMA table_info(productos)")}
        ingrediente_columns = {row[1] for row in conn.execute("PRAGMA table_info(ingredientes)")}
        venta_columns = {row[1] for row in conn.execute("PRAGMA table_info(ventas)")}
        corte_columns = {row[1] for row in conn.execute("PRAGMA table_info(cortes_caja)")}
        security_columns = {row[1] for row in conn.execute("PRAGMA table_info(configuracion_seguridad)")}
        cafeteria_columns = {row[1] for row in conn.execute("PRAGMA table_info(cafeteria_ventas)")}
        pago_cafeteria_columns = {row[1] for row in conn.execute("PRAGMA table_info(pagos_cafeteria_venta)")}
    finally:
        conn.close()

    assert "precio_uber_eats" in producto_columns
    assert "precio_cdmx" in producto_columns
    assert {"clave", "valor", "actualizado_en"}.issubset(security_columns)
    assert {"familia_id", "presentacion"}.issubset(producto_columns)
    assert "es_empaque" in ingrediente_columns
    assert "canal" in venta_columns
    assert "edicion_revision" in venta_columns
    assert {"estado", "motivo_estado", "turno", "periodo_inicio", "periodo_fin"}.issubset(corte_columns)
    assert {"retiros", "fondo_entregado", "recibido_por"}.issubset(corte_columns)
    assert "fecha_entrega" in cafeteria_columns
    assert "idempotency_key" in pago_cafeteria_columns


def test_alembic_upgrade_head_on_precreated_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'precreated.db'}"

    _run([
        sys.executable,
        "-c",
        "from app.core.database import Base, engine; import app.models; Base.metadata.create_all(bind=engine)",
    ], database_url)
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], database_url)
    current = _run([sys.executable, "-m", "alembic", "current"], database_url)

    assert ALEMBIC_HEAD in current.stdout


def test_ticket_revision_migration_keeps_old_ticket_and_is_repeatable(tmp_path):
    db_path = tmp_path / "legacy_ticket.db"
    url = f"sqlite:///{db_path}"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('b2c3d4e5f6a7');
            CREATE TABLE ventas (id INTEGER PRIMARY KEY, folio VARCHAR(30), total NUMERIC(14,2));
            INSERT INTO ventas VALUES (1, 'T-TEST', 190);
        """)
    for _ in range(2):
        _run([sys.executable, "-m", "alembic", "upgrade", "head"], url)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, folio, total, edicion_revision FROM ventas").fetchone() == (1, "T-TEST", 190, 0)
    _run([sys.executable, "-m", "alembic", "downgrade", "b2c3d4e5f6a7"], url)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, folio, total FROM ventas").fetchone() == (1, "T-TEST", 190)


def test_cdmx_migration_preserves_prices_stock_and_tickets_and_is_repeatable(tmp_path):
    db_path = tmp_path / "legacy_cdmx.db"
    url = f"sqlite:///{db_path}"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('c4d5e6f7a8b9');
            CREATE TABLE productos (id INTEGER PRIMARY KEY, precio_unitario NUMERIC(12,2),
                precio_cafeteria NUMERIC(12,2), precio_uber_eats NUMERIC(12,2), stock_actual NUMERIC(12,4));
            INSERT INTO productos VALUES (1, 100, 80, 120, 10);
            CREATE TABLE ventas (id INTEGER PRIMARY KEY, canal VARCHAR(20), total NUMERIC(14,2));
            INSERT INTO ventas VALUES (1, 'mostrador', 100);
        """)
    for _ in range(2):
        _run([sys.executable, "-m", "alembic", "upgrade", "head"], url)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT * FROM productos").fetchone() == (1, 100, 80, 120, 10, None)
        assert conn.execute("SELECT * FROM ventas").fetchone() == (1, "mostrador", 100)
    _run([sys.executable, "-m", "alembic", "downgrade", "c4d5e6f7a8b9"], url)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT * FROM productos").fetchone() == (1, 100, 80, 120, 10)


def test_runtime_guard_adds_cdmx_price_without_setting_prices_or_stock(tmp_path):
    from sqlalchemy import create_engine
    from app.core.schema_guard import ensure_runtime_schema

    db_path = tmp_path / "runtime_cdmx.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE productos (id INTEGER PRIMARY KEY, precio_unitario NUMERIC(12,2), stock_actual NUMERIC(12,4));
            INSERT INTO productos VALUES (1, 100, 10);
        """)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        ensure_runtime_schema(engine)
        ensure_runtime_schema(engine)
        with sqlite3.connect(db_path) as conn:
            assert conn.execute("SELECT precio_unitario, stock_actual, precio_cdmx FROM productos").fetchone() == (100, 10, None)
    finally:
        engine.dispose()


def _legacy_cafeteria_schema(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('7d91c0a64e28');
            CREATE TABLE cafeteria_ventas (id INTEGER PRIMARY KEY, folio VARCHAR(30),
                total NUMERIC(14,2), monto_pagado NUMERIC(14,2), fecha DATETIME);
            INSERT INTO cafeteria_ventas VALUES (1, 'CAF-ANTERIOR', 100, 25, '2026-08-01 12:00:00');
            CREATE TABLE pagos_cafeteria_venta (id INTEGER PRIMARY KEY, venta_id INTEGER,
                monto NUMERIC(14,2), fecha DATETIME);
            INSERT INTO pagos_cafeteria_venta VALUES (1, 1, 25, '2026-08-05 15:00:00');
        """)


def _assert_cafeteria_history_unchanged(db_path, *, upgraded):
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT id, folio, total, monto_pagado, fecha FROM cafeteria_ventas").fetchone() == (
            1, "CAF-ANTERIOR", 100, 25, "2026-08-01 12:00:00",
        )
        assert conn.execute("SELECT id, venta_id, monto, fecha FROM pagos_cafeteria_venta").fetchone() == (
            1, 1, 25, "2026-08-05 15:00:00",
        )
        if upgraded:
            assert conn.execute("SELECT fecha_entrega FROM cafeteria_ventas").fetchone() == (None,)
            assert conn.execute("SELECT idempotency_key FROM pagos_cafeteria_venta").fetchone() == (None,)
            indexes = {r[1]: r[2] for r in conn.execute("PRAGMA index_list(pagos_cafeteria_venta)")}
            assert indexes["ix_pagos_cafeteria_venta_idempotency_key"] == 1


def test_cafeteria_dates_migration_keeps_legacy_history_repeatable_and_reversible(tmp_path):
    db_path = tmp_path / "legacy_cafeteria.db"
    url = f"sqlite:///{db_path}"
    _legacy_cafeteria_schema(db_path)
    for _ in range(2):
        _run([sys.executable, "-m", "alembic", "upgrade", "head"], url)
        _assert_cafeteria_history_unchanged(db_path, upgraded=True)
    _run([sys.executable, "-m", "alembic", "downgrade", "7d91c0a64e28"], url)
    _assert_cafeteria_history_unchanged(db_path, upgraded=False)


def test_runtime_guard_adds_cafeteria_dates_and_retry_keys_without_backfill(tmp_path):
    from sqlalchemy import create_engine
    from app.core.schema_guard import ensure_runtime_schema

    db_path = tmp_path / "runtime_cafeteria.db"
    _legacy_cafeteria_schema(db_path)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        for _ in range(2):
            ensure_runtime_schema(engine)
            _assert_cafeteria_history_unchanged(db_path, upgraded=True)
    finally:
        engine.dispose()


def test_cash_handover_migration_preserves_legacy_cut(tmp_path):
    db_path = tmp_path / "legacy_corte.db"
    database_url = f"sqlite:///{db_path}"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version VALUES ('a1b2c3d4e5f6');
            CREATE TABLE cortes_caja (
                id INTEGER PRIMARY KEY,
                retiros NUMERIC(14, 2) NOT NULL DEFAULT 0,
                efectivo_real NUMERIC(14, 2) NOT NULL
            );
            INSERT INTO cortes_caja VALUES (1, 0, 5000);
        """)
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], database_url)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, retiros, efectivo_real, fondo_entregado, recibido_por FROM cortes_caja"
        ).fetchone()
    assert row == (1, 0, 5000, None, None)


def test_runtime_guard_adds_cash_handover_columns_without_changing_legacy_rows(tmp_path):
    from sqlalchemy import create_engine
    from app.core.schema_guard import ensure_runtime_schema

    db_path = tmp_path / "runtime_corte.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE cortes_caja (
                id INTEGER PRIMARY KEY,
                retiros NUMERIC(14, 2) NOT NULL DEFAULT 0,
                efectivo_real NUMERIC(14, 2) NOT NULL
            );
            INSERT INTO cortes_caja VALUES (1, 0, 5000);
        """)
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        ensure_runtime_schema(engine)
        ensure_runtime_schema(engine)
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT id, retiros, efectivo_real, fondo_entregado, recibido_por FROM cortes_caja"
            ).fetchone()
        assert row == (1, 0, 5000, None, None)
    finally:
        engine.dispose()


def test_alembic_adds_pedido_delivery_columns_to_legacy_schema(tmp_path):
    db_path = tmp_path / "legacy_pedidos.db"
    database_url = f"sqlite:///{db_path}"

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            );
            INSERT INTO alembic_version (version_num) VALUES ('e8f9a0b1c2d3');
            CREATE TABLE pedidos (
                id INTEGER PRIMARY KEY,
                folio VARCHAR(20) NOT NULL,
                idempotency_key VARCHAR(80),
                cliente_nombre VARCHAR(200) NOT NULL,
                cliente_telefono VARCHAR(20),
                fecha_entrega DATE NOT NULL,
                hora_entrega VARCHAR(10),
                lugar_entrega VARCHAR(300),
                estado VARCHAR(30) NOT NULL,
                origen VARCHAR(30) NOT NULL,
                creado_en DATETIME
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    _run([sys.executable, "-m", "alembic", "upgrade", "head"], database_url)

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(pedidos)")}
    finally:
        conn.close()

    assert {
        "anticipo",
        "total",
        "pagado",
        "creado_en",
        "repartidor_nombre",
        "direccion_entrega",
        "costo_envio",
        "en_ruta_en",
        "entregado_en",
        "actualizado_en",
    }.issubset(columns)


def test_alembic_creates_missing_pedido_detail_table(tmp_path):
    db_path = tmp_path / "legacy_pedidos_without_details.db"
    database_url = f"sqlite:///{db_path}"

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            );
            INSERT INTO alembic_version (version_num) VALUES ('f1a2b3c4d5e6');
            CREATE TABLE productos (id INTEGER PRIMARY KEY);
            CREATE TABLE pedidos (
                id INTEGER PRIMARY KEY,
                folio VARCHAR(20) NOT NULL,
                cliente_nombre VARCHAR(200) NOT NULL,
                fecha_entrega DATE NOT NULL,
                estado VARCHAR(30) NOT NULL,
                origen VARCHAR(30) NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    _run([sys.executable, "-m", "alembic", "upgrade", "head"], database_url)

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        detalle_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(detalles_pedido)")
        }
        pedido_columns = {row[1] for row in conn.execute("PRAGMA table_info(pedidos)")}
    finally:
        conn.close()

    assert "detalles_pedido" in tables
    assert {"pedido_id", "descripcion", "cantidad", "precio_unitario"}.issubset(
        detalle_columns
    )
    assert "creado_en" in pedido_columns


def test_alembic_repairs_existing_pedido_detail_table(tmp_path):
    db_path = tmp_path / "legacy_partial_details.db"
    database_url = f"sqlite:///{db_path}"

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            );
            INSERT INTO alembic_version (version_num) VALUES ('a7b8c9d0e1f2');
            CREATE TABLE detalles_pedido (
                id INTEGER PRIMARY KEY,
                pedido_id INTEGER
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    _run([sys.executable, "-m", "alembic", "upgrade", "head"], database_url)

    conn = sqlite3.connect(db_path)
    try:
        detalle_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(detalles_pedido)")
        }
    finally:
        conn.close()

    assert {
        "pedido_id",
        "producto_id",
        "descripcion",
        "cantidad",
        "precio_unitario",
        "notas",
    }.issubset(detalle_columns)


def test_alembic_recreates_empty_legacy_pedido_detail_table(tmp_path):
    db_path = tmp_path / "legacy_empty_bad_details.db"
    database_url = f"sqlite:///{db_path}"

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE alembic_version (
                version_num VARCHAR(32) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            );
            INSERT INTO alembic_version (version_num) VALUES ('c1d2e3f4a5b6');
            CREATE TABLE productos (id INTEGER PRIMARY KEY);
            CREATE TABLE pedidos (
                id INTEGER PRIMARY KEY,
                folio VARCHAR(20) NOT NULL,
                cliente_nombre VARCHAR(200) NOT NULL,
                cliente_telefono VARCHAR(20) NOT NULL,
                fecha_entrega DATE NOT NULL,
                estado VARCHAR(30) NOT NULL,
                origen VARCHAR(30) NOT NULL,
                productos TEXT NOT NULL
            );
            CREATE TABLE detalles_pedido (
                pedido INTEGER NOT NULL,
                producto TEXT NOT NULL,
                subtotal TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

    _run([sys.executable, "-m", "alembic", "upgrade", "head"], database_url)

    conn = sqlite3.connect(db_path)
    try:
        detalle_info = {
            row[1]: row for row in conn.execute("PRAGMA table_info(detalles_pedido)")
        }
        pedido_info = {
            row[1]: row for row in conn.execute("PRAGMA table_info(pedidos)")
        }
    finally:
        conn.close()

    assert {"id", "pedido_id", "producto_id", "descripcion"}.issubset(detalle_info)
    assert detalle_info["id"][5] == 1  # primary key
    assert pedido_info["cliente_telefono"][3] == 0
    assert pedido_info["productos"][3] == 0
