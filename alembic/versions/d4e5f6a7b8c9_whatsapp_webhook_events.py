"""whatsapp webhook replay protection

Revision ID: d4e5f6a7b8c9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-04 11:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
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
    if not _table_exists("whatsapp_webhook_events"):
        op.create_table(
            "whatsapp_webhook_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("message_id", sa.String(length=160), nullable=False),
            sa.Column("phone_number_id", sa.String(length=80), nullable=True),
            sa.Column("sender_phone", sa.String(length=30), nullable=True),
            sa.Column("message_type", sa.String(length=30), nullable=True),
            sa.Column("processed", sa.Boolean(), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("whatsapp_webhook_events", "ix_whatsapp_webhook_events_message_id"):
        op.create_index(
            "ix_whatsapp_webhook_events_message_id",
            "whatsapp_webhook_events",
            ["message_id"],
            unique=True,
        )
    if not _index_exists("whatsapp_webhook_events", "ix_whatsapp_webhook_events_phone_number_id"):
        op.create_index(
            "ix_whatsapp_webhook_events_phone_number_id",
            "whatsapp_webhook_events",
            ["phone_number_id"],
        )
    if not _index_exists("whatsapp_webhook_events", "ix_whatsapp_webhook_events_sender_phone"):
        op.create_index(
            "ix_whatsapp_webhook_events_sender_phone",
            "whatsapp_webhook_events",
            ["sender_phone"],
        )


def downgrade() -> None:
    if _table_exists("whatsapp_webhook_events"):
        if _index_exists("whatsapp_webhook_events", "ix_whatsapp_webhook_events_sender_phone"):
            op.drop_index("ix_whatsapp_webhook_events_sender_phone", table_name="whatsapp_webhook_events")
        if _index_exists("whatsapp_webhook_events", "ix_whatsapp_webhook_events_phone_number_id"):
            op.drop_index("ix_whatsapp_webhook_events_phone_number_id", table_name="whatsapp_webhook_events")
        if _index_exists("whatsapp_webhook_events", "ix_whatsapp_webhook_events_message_id"):
            op.drop_index("ix_whatsapp_webhook_events_message_id", table_name="whatsapp_webhook_events")
        op.drop_table("whatsapp_webhook_events")
