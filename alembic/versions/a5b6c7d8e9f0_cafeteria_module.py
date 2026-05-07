"""cafeteria sales module

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-05-06 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "a5b6c7d8e9f0"
down_revision: Union[str, Sequence[str], None] = "f4a5b6c7d8e9"
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
    if not _column_exists(table_name, column.name):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _column_exists(table_name, column_name):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.drop_column(column_name)


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


def upgrade() -> None:
    if _table_exists("productos"):
        _add_column_if_missing(
            "productos",
            sa.Column("precio_cafeteria", sa.Numeric(12, 2), nullable=True),
        )

    if not _table_exists("cafeteria_ventas"):
        op.create_table(
            "cafeteria_ventas",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("folio", sa.String(length=30), nullable=False),
            sa.Column("idempotency_key", sa.String(length=80), nullable=True),
            sa.Column("cafeteria_nombre", sa.String(length=200), nullable=False),
            sa.Column("contacto_nombre", sa.String(length=150), nullable=True),
            sa.Column("telefono", sa.String(length=30), nullable=True),
            sa.Column("usuario_id", sa.Integer(), nullable=False),
            sa.Column("subtotal", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("iva_0", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("iva_16", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("total_impuestos", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("total", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("monto_pagado", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("estado", sa.String(length=30), nullable=False, server_default="PENDIENTE"),
            sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
            sa.Column("fecha_credito", sa.Date(), nullable=True),
            sa.Column("notas", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("folio"),
            sa.UniqueConstraint("idempotency_key"),
        )

    if not _table_exists("detalles_cafeteria_venta"):
        op.create_table(
            "detalles_cafeteria_venta",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("venta_id", sa.Integer(), nullable=False),
            sa.Column("producto_id", sa.Integer(), nullable=False),
            sa.Column("cantidad", sa.Numeric(10, 4), nullable=False),
            sa.Column("precio_unitario", sa.Numeric(12, 2), nullable=False),
            sa.Column("subtotal", sa.Numeric(14, 2), nullable=False),
            sa.Column("tasa_iva", sa.Numeric(6, 4), nullable=False, server_default="0"),
            sa.Column("monto_iva", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.ForeignKeyConstraint(["producto_id"], ["productos.id"]),
            sa.ForeignKeyConstraint(["venta_id"], ["cafeteria_ventas.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _table_exists("pagos_cafeteria_venta"):
        op.create_table(
            "pagos_cafeteria_venta",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("venta_id", sa.Integer(), nullable=False),
            sa.Column("monto", sa.Numeric(14, 2), nullable=False),
            sa.Column("metodo_pago", sa.String(length=30), nullable=False),
            sa.Column("terminal", sa.String(length=30), nullable=False),
            sa.Column("referencia", sa.String(length=120), nullable=True),
            sa.Column("usuario_id", sa.Integer(), nullable=False),
            sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
            sa.ForeignKeyConstraint(["venta_id"], ["cafeteria_ventas.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    _create_index_if_missing("ix_cafeteria_ventas_folio", "cafeteria_ventas", ["folio"], unique=True)
    _create_index_if_missing(
        "ix_cafeteria_ventas_idempotency_key",
        "cafeteria_ventas",
        ["idempotency_key"],
        unique=True,
    )
    _create_index_if_missing("ix_cafeteria_ventas_cafeteria_nombre", "cafeteria_ventas", ["cafeteria_nombre"])
    _create_index_if_missing("ix_cafeteria_ventas_estado", "cafeteria_ventas", ["estado"])
    _create_index_if_missing("ix_cafeteria_ventas_fecha", "cafeteria_ventas", ["fecha"])
    _create_index_if_missing("ix_detalles_cafeteria_venta_venta_id", "detalles_cafeteria_venta", ["venta_id"])
    _create_index_if_missing("ix_detalles_cafeteria_venta_producto_id", "detalles_cafeteria_venta", ["producto_id"])
    _create_index_if_missing("ix_pagos_cafeteria_venta_venta_id", "pagos_cafeteria_venta", ["venta_id"])
    _create_index_if_missing("ix_pagos_cafeteria_venta_fecha", "pagos_cafeteria_venta", ["fecha"])


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_pagos_cafeteria_venta_fecha", "pagos_cafeteria_venta"),
        ("ix_pagos_cafeteria_venta_venta_id", "pagos_cafeteria_venta"),
        ("ix_detalles_cafeteria_venta_producto_id", "detalles_cafeteria_venta"),
        ("ix_detalles_cafeteria_venta_venta_id", "detalles_cafeteria_venta"),
        ("ix_cafeteria_ventas_fecha", "cafeteria_ventas"),
        ("ix_cafeteria_ventas_estado", "cafeteria_ventas"),
        ("ix_cafeteria_ventas_cafeteria_nombre", "cafeteria_ventas"),
        ("ix_cafeteria_ventas_idempotency_key", "cafeteria_ventas"),
        ("ix_cafeteria_ventas_folio", "cafeteria_ventas"),
    ):
        _drop_index_if_exists(index_name, table_name)

    for table_name in (
        "pagos_cafeteria_venta",
        "detalles_cafeteria_venta",
        "cafeteria_ventas",
    ):
        if _table_exists(table_name):
            op.drop_table(table_name)

    if _table_exists("productos"):
        _drop_column_if_exists("productos", "precio_cafeteria")
