"""Regression tests for Alembic bootstrap migrations."""

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_HEAD = "e8f9a0b1c2d3 (head)"


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
