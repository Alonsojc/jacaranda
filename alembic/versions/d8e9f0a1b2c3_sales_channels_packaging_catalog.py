"""Add sales channel prices and explicit packaging catalog.

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-09-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a1b2"
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
    if _table_exists("productos") and not _column_exists("productos", "precio_uber_eats"):
        op.add_column(
            "productos",
            sa.Column("precio_uber_eats", sa.Numeric(12, 2), nullable=True),
        )

    if _table_exists("ingredientes") and not _column_exists("ingredientes", "es_empaque"):
        op.add_column(
            "ingredientes",
            sa.Column(
                "es_empaque",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if _column_exists("ingredientes", "es_empaque"):
        if _table_exists("productos") and _column_exists("productos", "caja_ingrediente_id"):
            op.execute(text("""
                UPDATE ingredientes
                SET es_empaque = true
                WHERE id IN (
                    SELECT caja_ingrediente_id
                    FROM productos
                    WHERE caja_ingrediente_id IS NOT NULL
                )
            """))
        op.execute(text("""
            UPDATE ingredientes
            SET es_empaque = true
            WHERE lower(CAST(unidad_medida AS VARCHAR)) IN ('caja', 'bolsa')
        """))
        if not _index_exists("ingredientes", "ix_ingredientes_es_empaque"):
            op.create_index(
                "ix_ingredientes_es_empaque",
                "ingredientes",
                ["es_empaque"],
            )

    if _table_exists("ventas") and not _column_exists("ventas", "canal"):
        op.add_column(
            "ventas",
            sa.Column(
                "canal",
                sa.String(length=20),
                nullable=False,
                server_default="mostrador",
            ),
        )
    if _column_exists("ventas", "canal") and not _index_exists("ventas", "ix_ventas_canal"):
        op.create_index("ix_ventas_canal", "ventas", ["canal"])


def downgrade() -> None:
    if _index_exists("ventas", "ix_ventas_canal"):
        op.drop_index("ix_ventas_canal", table_name="ventas")
    if _column_exists("ventas", "canal"):
        op.drop_column("ventas", "canal")

    if _index_exists("ingredientes", "ix_ingredientes_es_empaque"):
        op.drop_index("ix_ingredientes_es_empaque", table_name="ingredientes")
    if _column_exists("ingredientes", "es_empaque"):
        op.drop_column("ingredientes", "es_empaque")

    if _column_exists("productos", "precio_uber_eats"):
        op.drop_column("productos", "precio_uber_eats")
