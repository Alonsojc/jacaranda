"""Add product packaging ingredient links.

Revision ID: b9c0d1e2f3a4
Revises: a5b6c7d8e9f0
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d8e9f0"
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


def _foreign_key_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return constraint_name in {
        fk["name"] for fk in inspect(op.get_bind()).get_foreign_keys(table_name)
    }


def upgrade() -> None:
    if not _table_exists("productos"):
        return

    with op.batch_alter_table("productos") as batch_op:
        if not _column_exists("productos", "caja_ingrediente_id"):
            batch_op.add_column(
                sa.Column("caja_ingrediente_id", sa.Integer(), nullable=True)
            )
        if not _column_exists("productos", "caja_cantidad"):
            batch_op.add_column(
                sa.Column(
                    "caja_cantidad",
                    sa.Numeric(12, 4),
                    nullable=False,
                    server_default="1",
                )
            )

    if (
        _table_exists("ingredientes")
        and not _foreign_key_exists(
            "productos", "fk_productos_caja_ingrediente_id_ingredientes"
        )
    ):
        with op.batch_alter_table("productos") as batch_op:
            batch_op.create_foreign_key(
                "fk_productos_caja_ingrediente_id_ingredientes",
                "ingredientes",
                ["caja_ingrediente_id"],
                ["id"],
            )


def downgrade() -> None:
    if not _table_exists("productos"):
        return

    if _foreign_key_exists("productos", "fk_productos_caja_ingrediente_id_ingredientes"):
        with op.batch_alter_table("productos") as batch_op:
            batch_op.drop_constraint(
                "fk_productos_caja_ingrediente_id_ingredientes",
                type_="foreignkey",
            )

    with op.batch_alter_table("productos") as batch_op:
        if _column_exists("productos", "caja_cantidad"):
            batch_op.drop_column("caja_cantidad")
        if _column_exists("productos", "caja_ingrediente_id"):
            batch_op.drop_column("caja_ingrediente_id")
