"""sprint3 cafeteria b2b operations

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
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


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _table_exists(table_name) and _column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def upgrade() -> None:
    if not _table_exists("cafeteria_clientes"):
        op.create_table(
            "cafeteria_clientes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nombre", sa.String(length=200), nullable=False),
            sa.Column("contacto_nombre", sa.String(length=150), nullable=True),
            sa.Column("telefono", sa.String(length=30), nullable=True),
            sa.Column("dias_credito", sa.Integer(), nullable=False, server_default="7"),
            sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("creado_por_id", sa.Integer(), nullable=True),
            sa.Column("actualizado_por_id", sa.Integer(), nullable=True),
            sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["actualizado_por_id"], ["usuarios.id"]),
            sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("nombre"),
        )

    if _table_exists("cafeteria_ventas"):
        _add_column_if_missing(
            "cafeteria_ventas",
            sa.Column("cafeteria_id", sa.Integer(), nullable=True),
        )
        _add_column_if_missing(
            "cafeteria_ventas",
            sa.Column("dias_credito", sa.Integer(), nullable=False, server_default="7"),
        )
        _add_column_if_missing(
            "cafeteria_ventas",
            sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=True),
        )
        op.execute("UPDATE cafeteria_ventas SET dias_credito = 7 WHERE dias_credito IS NULL")
        op.execute("UPDATE cafeteria_ventas SET actualizado_en = fecha WHERE actualizado_en IS NULL")

    _create_index_if_missing(
        "ix_cafeteria_clientes_nombre",
        "cafeteria_clientes",
        ["nombre"],
        unique=True,
    )
    _create_index_if_missing(
        "ix_cafeteria_clientes_activo",
        "cafeteria_clientes",
        ["activo"],
    )
    _create_index_if_missing(
        "ix_cafeteria_ventas_cafeteria_id",
        "cafeteria_ventas",
        ["cafeteria_id"],
    )


def downgrade() -> None:
    _drop_index_if_exists("ix_cafeteria_ventas_cafeteria_id", "cafeteria_ventas")
    _drop_index_if_exists("ix_cafeteria_clientes_activo", "cafeteria_clientes")
    _drop_index_if_exists("ix_cafeteria_clientes_nombre", "cafeteria_clientes")

    _drop_column_if_exists("cafeteria_ventas", "actualizado_en")
    _drop_column_if_exists("cafeteria_ventas", "dias_credito")
    _drop_column_if_exists("cafeteria_ventas", "cafeteria_id")

    if _table_exists("cafeteria_clientes"):
        op.drop_table("cafeteria_clientes")
