"""repair detalles_pedido legacy columns

Revision ID: c1d2e3f4a5b6
Revises: a7b8c9d0e1f2
Create Date: 2026-05-06 10:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
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
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(column)


def upgrade() -> None:
    if not _table_exists("detalles_pedido"):
        op.create_table(
            "detalles_pedido",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("pedido_id", sa.Integer(), nullable=False),
            sa.Column("producto_id", sa.Integer(), nullable=True),
            sa.Column("descripcion", sa.String(length=300), nullable=False),
            sa.Column("cantidad", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "precio_unitario",
                sa.Numeric(12, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notas", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"]),
            sa.ForeignKeyConstraint(["producto_id"], ["productos.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        return

    # Production had legacy detalles_pedido tables created outside Alembic.
    # Keep this additive so it can repair partially shaped tables safely.
    _add_column_if_missing(
        "detalles_pedido", sa.Column("pedido_id", sa.Integer(), nullable=True)
    )
    _add_column_if_missing(
        "detalles_pedido", sa.Column("producto_id", sa.Integer(), nullable=True)
    )
    _add_column_if_missing(
        "detalles_pedido",
        sa.Column(
            "descripcion",
            sa.String(length=300),
            nullable=False,
            server_default="",
        ),
    )
    _add_column_if_missing(
        "detalles_pedido",
        sa.Column("cantidad", sa.Integer(), nullable=False, server_default="1"),
    )
    _add_column_if_missing(
        "detalles_pedido",
        sa.Column(
            "precio_unitario",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )
    _add_column_if_missing(
        "detalles_pedido", sa.Column("notas", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    # Additive production repair migration; do not drop order detail data.
    pass
