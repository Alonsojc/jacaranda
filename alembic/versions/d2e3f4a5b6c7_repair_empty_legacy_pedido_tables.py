"""repair empty legacy pedido tables

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-06 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PEDIDOS_REQUIRED = {"id", "folio", "cliente_nombre", "fecha_entrega", "estado", "origen"}
DETALLES_REQUIRED = {"id", "pedido_id", "descripcion", "cantidad", "precio_unitario"}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _columns(table_name: str) -> list[dict]:
    if not _table_exists(table_name):
        return []
    return inspect(op.get_bind()).get_columns(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in _columns(table_name))


def _table_count(table_name: str) -> int:
    if not _table_exists(table_name):
        return 0
    return int(op.get_bind().execute(text(f"SELECT COUNT(*) FROM {_quote(table_name)}")).scalar() or 0)


def _create_detalles_pedido() -> None:
    op.create_table(
        "detalles_pedido",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pedido_id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=True),
        sa.Column("descripcion", sa.String(length=300), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("precio_unitario", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["pedido_id"], ["pedidos.id"]),
        sa.ForeignKeyConstraint(["producto_id"], ["productos.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(column)


def _relax_not_nulls(table_name: str, required_columns: set[str]) -> None:
    if not _table_exists(table_name):
        return
    bind = op.get_bind()
    for column in _columns(table_name):
        name = column["name"]
        if name in required_columns or column.get("nullable", True):
            continue
        if bind.dialect.name == "postgresql":
            op.execute(
                text(
                    f"ALTER TABLE {_quote(table_name)} "
                    f"ALTER COLUMN {_quote(name)} DROP NOT NULL"
                )
            )
        else:
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.alter_column(
                    name,
                    existing_type=column["type"],
                    nullable=True,
                )


def _normalize_detalle_types_postgres() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql" or not _table_exists("detalles_pedido"):
        return

    casts = {
        "pedido_id": "CASE WHEN {c}::text ~ '^\\d+$' THEN {c}::integer ELSE NULL END",
        "producto_id": "CASE WHEN {c} IS NULL OR {c}::text = '' THEN NULL WHEN {c}::text ~ '^\\d+$' THEN {c}::integer ELSE NULL END",
        "cantidad": "CASE WHEN {c}::text ~ '^\\d+$' THEN {c}::integer ELSE 1 END",
        "precio_unitario": "CASE WHEN {c}::text ~ '^-?\\d+(\\.\\d+)?$' THEN {c}::numeric ELSE 0 END",
    }
    target_types = {
        "pedido_id": "INTEGER",
        "producto_id": "INTEGER",
        "cantidad": "INTEGER",
        "precio_unitario": "NUMERIC(12, 2)",
    }
    for name, expression in casts.items():
        if not _column_exists("detalles_pedido", name):
            continue
        quoted = _quote(name)
        op.execute(
            text(
                f"ALTER TABLE {_quote('detalles_pedido')} "
                f"ALTER COLUMN {quoted} TYPE {target_types[name]} "
                f"USING {expression.format(c=quoted)}"
            )
        )


def upgrade() -> None:
    if _table_exists("detalles_pedido"):
        detalles_is_empty = _table_count("detalles_pedido") == 0
        pedidos_ready = _table_exists("pedidos")
        productos_ready = _table_exists("productos")
        pedidos_is_empty = _table_count("pedidos") == 0
        if detalles_is_empty and pedidos_is_empty and pedidos_ready and productos_ready:
            # Production had an empty legacy table with the wrong shape. Since
            # there is no order data to preserve, recreate it cleanly.
            op.drop_table("detalles_pedido")
            _create_detalles_pedido()
        else:
            _add_column_if_missing(
                "detalles_pedido",
                sa.Column("id", sa.Integer(), autoincrement=True, nullable=True),
            )
            _add_column_if_missing(
                "detalles_pedido", sa.Column("pedido_id", sa.Integer(), nullable=True)
            )
            _add_column_if_missing(
                "detalles_pedido", sa.Column("producto_id", sa.Integer(), nullable=True)
            )
            _add_column_if_missing(
                "detalles_pedido",
                sa.Column("descripcion", sa.String(length=300), nullable=False, server_default=""),
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
            _normalize_detalle_types_postgres()
            _relax_not_nulls("detalles_pedido", DETALLES_REQUIRED)
    elif _table_exists("pedidos"):
        _create_detalles_pedido()

    _relax_not_nulls("pedidos", PEDIDOS_REQUIRED)


def downgrade() -> None:
    # Production repair migration; do not reintroduce legacy constraints.
    pass
