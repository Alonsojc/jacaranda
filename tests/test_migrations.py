"""Regression tests for Alembic bootstrap migrations."""

import os
import subprocess
import sys
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_HEAD = "f1a2b3c4d5e6 (head)"


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
    database_url = f"sqlite:///{tmp_path / 'clean.db'}"

    _run([sys.executable, "-m", "alembic", "upgrade", "head"], database_url)
    current = _run([sys.executable, "-m", "alembic", "current"], database_url)

    assert ALEMBIC_HEAD in current.stdout


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
        "repartidor_nombre",
        "direccion_entrega",
        "costo_envio",
        "en_ruta_en",
        "entregado_en",
        "actualizado_en",
    }.issubset(columns)
