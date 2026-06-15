"""sprint2 egresos operacion

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-06-14
"""

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return column_name in {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def _drop_column_if_exists(table_name: str, column_name: str) -> None:
    if _table_exists(table_name) and _column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _table_exists(table_name) and not _index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if _table_exists(table_name) and _index_exists(table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def _fk_or_plain_column(name: str, type_: Any, target: str, **kwargs) -> sa.Column:
    target_table = target.split(".", 1)[0]
    if _table_exists(target_table):
        return sa.Column(name, type_, sa.ForeignKey(target), **kwargs)
    return sa.Column(name, type_, **kwargs)


def upgrade() -> None:
    _add_column_if_missing("egresos", _fk_or_plain_column("proveedor_id", sa.Integer(), "proveedores.id", nullable=True))
    _add_column_if_missing("egresos", sa.Column("origen", sa.String(length=30), nullable=False, server_default="manual"))
    _add_column_if_missing("egresos", sa.Column("ocr_payload", sa.Text(), nullable=True))
    _add_column_if_missing("egresos", _fk_or_plain_column("actualizado_por_id", sa.Integer(), "usuarios.id", nullable=True))
    _add_column_if_missing("egresos", _fk_or_plain_column("anulado_por_id", sa.Integer(), "usuarios.id", nullable=True))
    _add_column_if_missing("egresos", sa.Column("anulado_motivo", sa.Text(), nullable=True))
    _add_column_if_missing("egresos", sa.Column("anulado_en", sa.DateTime(timezone=True), nullable=True))
    _create_index_if_missing("ix_egresos_proveedor_id", "egresos", ["proveedor_id"])
    _create_index_if_missing("ix_egresos_origen", "egresos", ["origen"])

    _add_column_if_missing(
        "gastos_fijos",
        sa.Column("categoria", sa.String(length=60), nullable=False, server_default="recurrente"),
    )
    _add_column_if_missing(
        "gastos_fijos",
        sa.Column("metodo_pago", sa.String(length=30), nullable=False, server_default="transferencia"),
    )
    _add_column_if_missing(
        "gastos_fijos",
        _fk_or_plain_column("proveedor_id", sa.Integer(), "proveedores.id", nullable=True),
    )
    _add_column_if_missing("gastos_fijos", sa.Column("proveedor", sa.String(length=150), nullable=True))
    _add_column_if_missing("gastos_fijos", _fk_or_plain_column("creado_por_id", sa.Integer(), "usuarios.id", nullable=True))
    _add_column_if_missing(
        "gastos_fijos",
        _fk_or_plain_column("actualizado_por_id", sa.Integer(), "usuarios.id", nullable=True),
    )
    _add_column_if_missing(
        "gastos_fijos",
        _fk_or_plain_column("desactivado_por_id", sa.Integer(), "usuarios.id", nullable=True),
    )
    _add_column_if_missing("gastos_fijos", sa.Column("desactivado_motivo", sa.Text(), nullable=True))
    _add_column_if_missing("gastos_fijos", sa.Column("desactivado_en", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("gastos_fijos", sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=True))
    _create_index_if_missing("ix_gastos_fijos_proveedor_id", "gastos_fijos", ["proveedor_id"])


def downgrade() -> None:
    _drop_index_if_exists("ix_gastos_fijos_proveedor_id", "gastos_fijos")
    for column_name in [
        "actualizado_en",
        "desactivado_en",
        "desactivado_motivo",
        "desactivado_por_id",
        "actualizado_por_id",
        "creado_por_id",
        "proveedor",
        "proveedor_id",
        "metodo_pago",
        "categoria",
    ]:
        _drop_column_if_exists("gastos_fijos", column_name)

    _drop_index_if_exists("ix_egresos_origen", "egresos")
    _drop_index_if_exists("ix_egresos_proveedor_id", "egresos")
    for column_name in [
        "anulado_en",
        "anulado_motivo",
        "anulado_por_id",
        "actualizado_por_id",
        "ocr_payload",
        "origen",
        "proveedor_id",
    ]:
        _drop_column_if_exists("egresos", column_name)
