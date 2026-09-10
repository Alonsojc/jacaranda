"""Store cash-closing periods so multiple shifts can close in one day.

Revision ID: a1b2c3d4e5f6
Revises: f8a9b0c1d2e3
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
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
        if not _column_exists("cortes_caja", "turno"):
            batch_op.add_column(sa.Column("turno", sa.Integer(), nullable=True))
        if not _column_exists("cortes_caja", "periodo_inicio"):
            batch_op.add_column(sa.Column("periodo_inicio", sa.DateTime(timezone=True), nullable=True))
        if not _column_exists("cortes_caja", "periodo_fin"):
            batch_op.add_column(sa.Column("periodo_fin", sa.DateTime(timezone=True), nullable=True))
    if not _index_exists("cortes_caja", "ix_cortes_caja_periodo_inicio"):
        op.create_index("ix_cortes_caja_periodo_inicio", "cortes_caja", ["periodo_inicio"])
    if not _index_exists("cortes_caja", "ix_cortes_caja_periodo_fin"):
        op.create_index("ix_cortes_caja_periodo_fin", "cortes_caja", ["periodo_fin"])


def downgrade() -> None:
    if "cortes_caja" not in inspect(op.get_bind()).get_table_names():
        return
    if _index_exists("cortes_caja", "ix_cortes_caja_periodo_fin"):
        op.drop_index("ix_cortes_caja_periodo_fin", table_name="cortes_caja")
    if _index_exists("cortes_caja", "ix_cortes_caja_periodo_inicio"):
        op.drop_index("ix_cortes_caja_periodo_inicio", table_name="cortes_caja")
    with op.batch_alter_table("cortes_caja") as batch_op:
        if _column_exists("cortes_caja", "periodo_fin"):
            batch_op.drop_column("periodo_fin")
        if _column_exists("cortes_caja", "periodo_inicio"):
            batch_op.drop_column("periodo_inicio")
        if _column_exists("cortes_caja", "turno"):
            batch_op.drop_column("turno")
