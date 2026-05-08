"""clip pinpad terminal payments

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in inspect(op.get_bind()).get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(idx["name"] == index_name for idx in inspect(op.get_bind()).get_indexes(table_name))


def upgrade() -> None:
    if _table_exists("ventas"):
        with op.batch_alter_table("ventas") as batch_op:
            if not _column_exists("ventas", "pago_integrado"):
                batch_op.add_column(
                    sa.Column(
                        "pago_integrado",
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("false"),
                    )
                )
            if not _column_exists("ventas", "pago_proveedor"):
                batch_op.add_column(sa.Column("pago_proveedor", sa.String(length=30), nullable=True))
            if not _column_exists("ventas", "pago_externo_id"):
                batch_op.add_column(sa.Column("pago_externo_id", sa.String(length=120), nullable=True))
            if not _column_exists("ventas", "pago_externo_estado"):
                batch_op.add_column(sa.Column("pago_externo_estado", sa.String(length=60), nullable=True))
            if not _column_exists("ventas", "pago_externo_referencia"):
                batch_op.add_column(sa.Column("pago_externo_referencia", sa.String(length=120), nullable=True))
            if not _column_exists("ventas", "pago_externo_payload"):
                batch_op.add_column(sa.Column("pago_externo_payload", sa.Text(), nullable=True))
            if not _column_exists("ventas", "pago_verificado_en"):
                batch_op.add_column(sa.Column("pago_verificado_en", sa.DateTime(timezone=True), nullable=True))

        if not _index_exists("ventas", "ix_ventas_pago_proveedor"):
            op.create_index("ix_ventas_pago_proveedor", "ventas", ["pago_proveedor"])
        if not _index_exists("ventas", "ix_ventas_pago_externo_id"):
            op.create_index("ix_ventas_pago_externo_id", "ventas", ["pago_externo_id"])
        if not _index_exists("ventas", "ix_ventas_pago_externo_referencia"):
            op.create_index("ix_ventas_pago_externo_referencia", "ventas", ["pago_externo_referencia"])

    if not _table_exists("clip_webhook_events"):
        op.create_table(
            "clip_webhook_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.String(length=160), nullable=False),
            sa.Column("event_type", sa.String(length=100), nullable=True),
            sa.Column("payment_id", sa.String(length=120), nullable=True),
            sa.Column("venta_id", sa.Integer(), nullable=True),
            sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("payload_json", sa.Text(), nullable=True),
            sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["venta_id"], ["ventas.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("clip_webhook_events", "ix_clip_webhook_events_event_id"):
        op.create_index(
            "ix_clip_webhook_events_event_id",
            "clip_webhook_events",
            ["event_id"],
            unique=True,
        )
    if not _index_exists("clip_webhook_events", "ix_clip_webhook_events_payment_id"):
        op.create_index(
            "ix_clip_webhook_events_payment_id",
            "clip_webhook_events",
            ["payment_id"],
        )
    if not _index_exists("clip_webhook_events", "ix_clip_webhook_events_venta_id"):
        op.create_index(
            "ix_clip_webhook_events_venta_id",
            "clip_webhook_events",
            ["venta_id"],
        )


def downgrade() -> None:
    if _table_exists("clip_webhook_events"):
        for index_name in (
            "ix_clip_webhook_events_venta_id",
            "ix_clip_webhook_events_payment_id",
            "ix_clip_webhook_events_event_id",
        ):
            if _index_exists("clip_webhook_events", index_name):
                op.drop_index(index_name, table_name="clip_webhook_events")
        op.drop_table("clip_webhook_events")

    if _table_exists("ventas"):
        for index_name in (
            "ix_ventas_pago_externo_referencia",
            "ix_ventas_pago_externo_id",
            "ix_ventas_pago_proveedor",
        ):
            if _index_exists("ventas", index_name):
                op.drop_index(index_name, table_name="ventas")

        with op.batch_alter_table("ventas") as batch_op:
            for column_name in (
                "pago_verificado_en",
                "pago_externo_payload",
                "pago_externo_referencia",
                "pago_externo_estado",
                "pago_externo_id",
                "pago_proveedor",
                "pago_integrado",
            ):
                if _column_exists("ventas", column_name):
                    batch_op.drop_column(column_name)
