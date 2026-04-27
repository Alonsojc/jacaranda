"""idempotency and webhook event replay protection

Revision ID: 9b7c6d5e4f31
Revises: 5866f5d625db
Create Date: 2026-04-27 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "9b7c6d5e4f31"
down_revision: Union[str, Sequence[str], None] = "5866f5d625db"
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


def upgrade() -> None:
    if not _column_exists("ventas", "idempotency_key"):
        op.add_column("ventas", sa.Column("idempotency_key", sa.String(length=80), nullable=True))
    if not _index_exists("ventas", "ix_ventas_idempotency_key"):
        op.create_index("ix_ventas_idempotency_key", "ventas", ["idempotency_key"], unique=True)

    if not _column_exists("pedidos", "idempotency_key"):
        op.add_column("pedidos", sa.Column("idempotency_key", sa.String(length=80), nullable=True))
    if not _index_exists("pedidos", "ix_pedidos_idempotency_key"):
        op.create_index("ix_pedidos_idempotency_key", "pedidos", ["idempotency_key"], unique=True)

    if not _table_exists("conekta_webhook_events"):
        op.create_table(
            "conekta_webhook_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("event_id", sa.String(length=120), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=True),
            sa.Column("order_id_externo", sa.String(length=100), nullable=True),
            sa.Column("processed", sa.Boolean(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("conekta_webhook_events", "ix_conekta_webhook_events_event_id"):
        op.create_index("ix_conekta_webhook_events_event_id", "conekta_webhook_events", ["event_id"], unique=True)
    if not _index_exists("conekta_webhook_events", "ix_conekta_webhook_events_order_id_externo"):
        op.create_index("ix_conekta_webhook_events_order_id_externo", "conekta_webhook_events", ["order_id_externo"])


def downgrade() -> None:
    op.drop_index("ix_conekta_webhook_events_order_id_externo", table_name="conekta_webhook_events")
    op.drop_index("ix_conekta_webhook_events_event_id", table_name="conekta_webhook_events")
    op.drop_table("conekta_webhook_events")

    op.drop_index("ix_pedidos_idempotency_key", table_name="pedidos")
    op.drop_column("pedidos", "idempotency_key")

    op.drop_index("ix_ventas_idempotency_key", table_name="ventas")
    op.drop_column("ventas", "idempotency_key")
