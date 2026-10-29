"""CI-only disposable PostgreSQL proof. Never accepts an operational database."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models.asistencia import ChecadaAsistencia, SincronizacionAsistencia
from app.models.empleado import RegistroAsistencia, RegistroNomina
from app.models.usuario import Usuario
from app.services.asistencia_service import import_records, query_records
from app.services.crosschex_service import ClockRecord


@pytest.mark.skipif(not os.environ.get("ASISTENCIA_TEST_DATABASE_URL"), reason="Requires empty, disposable PostgreSQL fixture")
def test_postgres_migration_concurrency_and_payroll_isolation():
    raw_url = os.environ["ASISTENCIA_TEST_DATABASE_URL"]
    url = make_url(raw_url)
    assert url.drivername.startswith("postgresql")
    assert url.host in {"localhost", "127.0.0.1"}
    assert url.database == "jacaranda_asistencia_test"
    engine = create_engine(raw_url)
    try:
        assert inspect(engine).get_table_names() == [], "Fixture must be empty; do not reuse a business database"
        env = {**os.environ, "DATABASE_URL": raw_url}
        result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                                env=env, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        with Session(engine) as db:
            db.add(Usuario(id=1, nombre="Fixture", email="fixture@example.test", hashed_password="not-a-password"))
            db.commit()
        raw = ClockRecord.model_validate({
            "checktime": "2026-10-28T09:30:00-06:00", "checktype": 128,
            "employee": {"workno": "001", "first_name": "Test", "last_name": "Only"},
            "device": {"serial_number": "FIXTURE", "name": "Test"},
        })
        begin = datetime(2026, 10, 28, 6, tzinfo=timezone.utc)
        end = datetime(2026, 10, 29, 6, tzinfo=timezone.utc)
        barrier = Barrier(2)
        def run():
            with Session(engine) as db:
                barrier.wait(timeout=10)
                return import_records(db, [raw], "us:fixture", begin, end, 0, SimpleNamespace(id=1, nombre="Fixture"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        assert sorted(r["nuevas"] for r in results) == [0, 1]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(ChecadaAsistencia)) == 1
            assert db.scalar(select(func.count()).select_from(SincronizacionAsistencia)) == 2
            assert db.scalar(select(func.count()).select_from(RegistroAsistencia)) == 0
            assert db.scalar(select(func.count()).select_from(RegistroNomina)) == 0
            rows = query_records(db, "us:fixture", begin, end)
            assert date.fromisoformat(rows[0]["fecha"][:10]) == date(2026, 10, 28)
            assert rows[0]["fecha"].endswith("-06:00")
    finally:
        engine.dispose()
