"""Add auditable lifecycle fields to cash closings.

Revision ID: f8a9b0c1d2e3
Revises: e1f2a3b4c5d6
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table_name: str, column_name: str) -> bool:
    if table_name not in inspect(op.get_bind()).get_table_names():
        return False
    return column_name in {
        column["name"] for column in inspect(op.get_bind()).get_columns(table_name)
    }


def _index_exists(table_name: str, index_name: str) -> bool:
    if table_name not in inspect(op.get_bind()).get_table_names():
        return False
    return index_name in {
        index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)
    }


def upgrade() -> None:
    if "cortes_caja" not in inspect(op.get_bind()).get_table_names():
        return
    with op.batch_alter_table("cortes_caja") as batch_op:
        if not _column_exists("cortes_caja", "estado"):
            batch_op.add_column(
                sa.Column(
                    "estado",
                    sa.String(length=20),
                    nullable=False,
                    server_default="cerrado",
                )
            )
        if not _column_exists("cortes_caja", "motivo_estado"):
            batch_op.add_column(sa.Column("motivo_estado", sa.Text(), nullable=True))
    if not _index_exists("cortes_caja", "ix_cortes_caja_estado"):
        op.create_index("ix_cortes_caja_estado", "cortes_caja", ["estado"])


def downgrade() -> None:
    if "cortes_caja" not in inspect(op.get_bind()).get_table_names():
        return
    if _index_exists("cortes_caja", "ix_cortes_caja_estado"):
        op.drop_index("ix_cortes_caja_estado", table_name="cortes_caja")
    with op.batch_alter_table("cortes_caja") as batch_op:
        if _column_exists("cortes_caja", "motivo_estado"):
            batch_op.drop_column("motivo_estado")
        if _column_exists("cortes_caja", "estado"):
            batch_op.drop_column("estado")
