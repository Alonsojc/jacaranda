"""pedido delivery and sync columns

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-05-06 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
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
    if not _column_exists(table_name, column.name):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _column_exists(table_name, column_name):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_column(column_name)


def upgrade() -> None:
    if not _table_exists("pedidos"):
        return

    # These are intentionally additive and idempotent. Some production
    # deployments bootstrapped tables with create_all before these fields
    # existed, so Alembic can be at head while the real table is missing them.
    _add_column_if_missing(
        "pedidos", sa.Column("cliente_id", sa.Integer(), nullable=True)
    )
    _add_column_if_missing("pedidos", sa.Column("notas", sa.Text(), nullable=True))
    _add_column_if_missing(
        "pedidos", sa.Column("notas_internas", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "pedidos",
        sa.Column("pagado", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        "pedidos",
        sa.Column("anticipo", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "pedidos",
        sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "pedidos", sa.Column("repartidor_nombre", sa.String(200), nullable=True)
    )
    _add_column_if_missing(
        "pedidos", sa.Column("repartidor_telefono", sa.String(20), nullable=True)
    )
    _add_column_if_missing(
        "pedidos", sa.Column("direccion_entrega", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "pedidos", sa.Column("referencia_entrega", sa.String(300), nullable=True)
    )
    _add_column_if_missing(
        "pedidos",
        sa.Column("costo_envio", sa.Numeric(10, 2), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "pedidos", sa.Column("en_ruta_en", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column_if_missing(
        "pedidos", sa.Column("entregado_en", sa.DateTime(timezone=True), nullable=True)
    )
    _add_column_if_missing(
        "pedidos", sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    if not _table_exists("pedidos"):
        return

    for column_name in (
        "actualizado_en",
        "entregado_en",
        "en_ruta_en",
        "costo_envio",
        "referencia_entrega",
        "direccion_entrega",
        "repartidor_telefono",
        "repartidor_nombre",
    ):
        _drop_column_if_exists("pedidos", column_name)
