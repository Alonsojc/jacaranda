"""sprint7 seguridad permisos auditoria

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-06-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {
        column["name"] for column in inspect(op.get_bind()).get_columns(table_name)
    }


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _table_exists(table_name) and _column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def _add_postgres_role_values() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    enum_exists = bind.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'rolusuario')")
    ).scalar()
    if not enum_exists:
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE rolusuario ADD VALUE IF NOT EXISTS 'PRODUCCION'")
        op.execute("ALTER TYPE rolusuario ADD VALUE IF NOT EXISTS 'CONSULTA'")


def upgrade() -> None:
    _add_postgres_role_values()
    _add_column_if_missing("log_auditoria", sa.Column("motivo", sa.Text(), nullable=True))


def downgrade() -> None:
    _drop_column_if_exists("log_auditoria", "motivo")
    # PostgreSQL enum values are intentionally left in place; removing enum
    # values safely requires rebuilding dependent columns and can break data.
