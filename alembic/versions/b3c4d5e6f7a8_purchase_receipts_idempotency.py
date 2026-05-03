"""purchase receipt idempotency

Revision ID: b3c4d5e6f7a8
Revises: 9b7c6d5e4f31
Create Date: 2026-05-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "9b7c6d5e4f31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {
        index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)
    }


def upgrade() -> None:
    if not _table_exists("recepciones_orden_compra"):
        op.create_table(
            "recepciones_orden_compra",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("orden_id", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=80), nullable=True),
            sa.Column("usuario_id", sa.Integer(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["orden_id"], ["ordenes_compra.id"]),
            sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("recepciones_orden_compra", "ix_recepciones_oc_orden_id"):
        op.create_index(
            "ix_recepciones_oc_orden_id",
            "recepciones_orden_compra",
            ["orden_id"],
        )
    if not _index_exists(
        "recepciones_orden_compra", "ix_recepciones_oc_idempotency_key"
    ):
        op.create_index(
            "ix_recepciones_oc_idempotency_key",
            "recepciones_orden_compra",
            ["idempotency_key"],
            unique=True,
        )


def downgrade() -> None:
    if _table_exists("recepciones_orden_compra"):
        if _index_exists(
            "recepciones_orden_compra", "ix_recepciones_oc_idempotency_key"
        ):
            op.drop_index(
                "ix_recepciones_oc_idempotency_key",
                table_name="recepciones_orden_compra",
            )
        if _index_exists("recepciones_orden_compra", "ix_recepciones_oc_orden_id"):
            op.drop_index(
                "ix_recepciones_oc_orden_id",
                table_name="recepciones_orden_compra",
            )
        op.drop_table("recepciones_orden_compra")
