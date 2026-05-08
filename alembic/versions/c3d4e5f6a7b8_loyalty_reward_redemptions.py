"""Add loyalty reward redemption fields to sales.

Revision ID: c3d4e5f6a7b8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
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


def upgrade() -> None:
    if not _table_exists("ventas"):
        return

    with op.batch_alter_table("ventas") as batch_op:
        if not _column_exists("ventas", "recompensa_lealtad_canjeada"):
            batch_op.add_column(
                sa.Column(
                    "recompensa_lealtad_canjeada",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                )
            )
        if not _column_exists("ventas", "recompensa_lealtad_nombre"):
            batch_op.add_column(sa.Column("recompensa_lealtad_nombre", sa.String(120)))
        if not _column_exists("ventas", "recompensa_lealtad_monto"):
            batch_op.add_column(
                sa.Column(
                    "recompensa_lealtad_monto",
                    sa.Numeric(14, 2),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    if not _table_exists("ventas"):
        return

    with op.batch_alter_table("ventas") as batch_op:
        if _column_exists("ventas", "recompensa_lealtad_monto"):
            batch_op.drop_column("recompensa_lealtad_monto")
        if _column_exists("ventas", "recompensa_lealtad_nombre"):
            batch_op.drop_column("recompensa_lealtad_nombre")
        if _column_exists("ventas", "recompensa_lealtad_canjeada"):
            batch_op.drop_column("recompensa_lealtad_canjeada")
