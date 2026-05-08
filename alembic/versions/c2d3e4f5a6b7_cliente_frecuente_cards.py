"""Add cliente frecuente card fields.

Revision ID: c2d3e4f5a6b7
Revises: b9c0d1e2f3a4
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
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


def upgrade() -> None:
    if not _table_exists("clientes"):
        return

    with op.batch_alter_table("clientes") as batch_op:
        if not _column_exists("clientes", "cliente_frecuente"):
            batch_op.add_column(
                sa.Column(
                    "cliente_frecuente",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                )
            )
        if not _column_exists("clientes", "monto_lealtad_acumulado"):
            batch_op.add_column(
                sa.Column(
                    "monto_lealtad_acumulado",
                    sa.Numeric(14, 2),
                    nullable=False,
                    server_default="0",
                )
            )
        if not _column_exists("clientes", "recompensas_lealtad_canjeadas"):
            batch_op.add_column(
                sa.Column(
                    "recompensas_lealtad_canjeadas",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )

    if _column_exists("clientes", "tarjeta_qr") and not _index_exists(
        "clientes", "ix_clientes_tarjeta_qr"
    ):
        op.create_index("ix_clientes_tarjeta_qr", "clientes", ["tarjeta_qr"])


def downgrade() -> None:
    if not _table_exists("clientes"):
        return

    if _index_exists("clientes", "ix_clientes_tarjeta_qr"):
        op.drop_index("ix_clientes_tarjeta_qr", table_name="clientes")

    with op.batch_alter_table("clientes") as batch_op:
        if _column_exists("clientes", "recompensas_lealtad_canjeadas"):
            batch_op.drop_column("recompensas_lealtad_canjeadas")
        if _column_exists("clientes", "monto_lealtad_acumulado"):
            batch_op.drop_column("monto_lealtad_acumulado")
        if _column_exists("clientes", "cliente_frecuente"):
            batch_op.drop_column("cliente_frecuente")
