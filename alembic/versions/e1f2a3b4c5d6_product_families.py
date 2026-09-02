"""Add formal product families and presentation links.

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-09-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
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


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return constraint_name in {
        constraint["name"]
        for constraint in inspect(op.get_bind()).get_unique_constraints(table_name)
    }


def upgrade() -> None:
    if not _table_exists("familias_producto"):
        op.create_table(
            "familias_producto",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("nombre", sa.String(length=200), nullable=False, unique=True),
            sa.Column(
                "activo",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "creado_en",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
    if not _index_exists("familias_producto", "ix_familias_producto_nombre"):
        op.create_index(
            "ix_familias_producto_nombre",
            "familias_producto",
            ["nombre"],
        )

    needs_familia_id = _table_exists("productos") and not _column_exists(
        "productos", "familia_id"
    )
    needs_presentacion = _table_exists("productos") and not _column_exists(
        "productos", "presentacion"
    )
    if needs_familia_id or needs_presentacion:
        # batch mode also supports old SQLite databases where ALTER TABLE
        # cannot add a foreign key constraint directly.
        with op.batch_alter_table("productos") as batch_op:
            if needs_familia_id:
                batch_op.add_column(sa.Column("familia_id", sa.Integer(), nullable=True))
            if needs_presentacion:
                batch_op.add_column(
                    sa.Column("presentacion", sa.String(length=100), nullable=True)
                )
            if needs_familia_id:
                batch_op.create_foreign_key(
                    "fk_productos_familia",
                    "familias_producto",
                    ["familia_id"],
                    ["id"],
                )
    if _column_exists("productos", "familia_id") and not _index_exists(
        "productos", "ix_productos_familia_id"
    ):
        op.create_index("ix_productos_familia_id", "productos", ["familia_id"])
    if (
        _column_exists("productos", "presentacion")
        and not _unique_constraint_exists("productos", "uq_productos_familia_presentacion")
        and not _index_exists("productos", "ux_productos_familia_presentacion")
    ):
        op.create_index(
            "ux_productos_familia_presentacion",
            "productos",
            ["familia_id", "presentacion"],
            unique=True,
        )


def downgrade() -> None:
    if _index_exists("productos", "ux_productos_familia_presentacion"):
        op.drop_index("ux_productos_familia_presentacion", table_name="productos")
    if _index_exists("productos", "ix_productos_familia_id"):
        op.drop_index("ix_productos_familia_id", table_name="productos")
    if _table_exists("productos") and (
        _column_exists("productos", "presentacion")
        or _column_exists("productos", "familia_id")
    ):
        with op.batch_alter_table("productos") as batch_op:
            if _unique_constraint_exists(
                "productos", "uq_productos_familia_presentacion"
            ):
                batch_op.drop_constraint(
                    "uq_productos_familia_presentacion", type_="unique"
                )
            if _column_exists("productos", "presentacion"):
                batch_op.drop_column("presentacion")
            if _column_exists("productos", "familia_id"):
                batch_op.drop_column("familia_id")

    if _index_exists("familias_producto", "ix_familias_producto_nombre"):
        op.drop_index("ix_familias_producto_nombre", table_name="familias_producto")
    if _table_exists("familias_producto"):
        op.drop_table("familias_producto")
