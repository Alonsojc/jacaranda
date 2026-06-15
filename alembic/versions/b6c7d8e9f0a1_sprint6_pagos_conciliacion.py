"""sprint6 pagos conciliacion

Revision ID: b6c7d8e9f0a1
Revises: a8b9c0d1e2f3
Create Date: 2026-06-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
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


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {
        index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)
    }


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _table_exists(table_name) and _column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _table_exists(table_name) and _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def upgrade() -> None:
    _add_column_if_missing("pagos_venta", sa.Column("terminal", sa.String(length=20), nullable=True))
    _add_column_if_missing("pagos_venta", sa.Column("proveedor", sa.String(length=30), nullable=True))
    _add_column_if_missing(
        "pagos_venta",
        sa.Column("estado", sa.String(length=20), nullable=False, server_default="pagado"),
    )
    _add_column_if_missing("pagos_venta", sa.Column("pago_externo_id", sa.String(length=120), nullable=True))
    _create_index_if_missing("ix_pagos_venta_proveedor", "pagos_venta", ["proveedor"])
    _create_index_if_missing("ix_pagos_venta_pago_externo_id", "pagos_venta", ["pago_externo_id"])


def downgrade() -> None:
    _drop_index_if_exists("ix_pagos_venta_pago_externo_id", "pagos_venta")
    _drop_index_if_exists("ix_pagos_venta_proveedor", "pagos_venta")
    _drop_column_if_exists("pagos_venta", "pago_externo_id")
    _drop_column_if_exists("pagos_venta", "estado")
    _drop_column_if_exists("pagos_venta", "proveedor")
    _drop_column_if_exists("pagos_venta", "terminal")
