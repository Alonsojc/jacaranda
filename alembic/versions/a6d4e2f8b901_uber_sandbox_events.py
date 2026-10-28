"""Add an isolated inbox for signed sandbox Uber events."""

from alembic import op
import sqlalchemy as sa

revision = "a6d4e2f8b901"
down_revision = "94c2a8e1d605"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "uber_sandbox_events" not in tables:
        _create_events()
    if "uber_sandbox_orders" not in tables:
        op.create_table(
            "uber_sandbox_orders",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("client_id", sa.String(160), nullable=False),
            sa.Column("store_id", sa.String(36), nullable=False),
            sa.Column("order_id", sa.String(36), nullable=False),
            sa.Column("state", sa.String(40), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("pending_request_key", sa.String(36), nullable=True),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("client_id", "store_id", "order_id", name="uq_uber_sandbox_order"),
        )
    if "uber_sandbox_actions" not in tables:
        op.create_table(
            "uber_sandbox_actions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("client_id", sa.String(160), nullable=False),
            sa.Column("store_id", sa.String(36), nullable=False),
            sa.Column("order_id", sa.String(36), nullable=False),
            sa.Column("request_key", sa.String(36), nullable=False),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("action", sa.String(20), nullable=False),
            sa.Column("estado", sa.String(20), nullable=False),
            sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("client_id", "store_id", "request_key", name="uq_uber_sandbox_action"),
        )
        op.create_index("ix_uber_sandbox_actions_order_id", "uber_sandbox_actions", ["order_id"])


def _create_events():
    op.create_table(
        "uber_sandbox_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(160), nullable=False),
        sa.Column("store_id", sa.String(36), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("event_time", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("estado", sa.String(30), nullable=False),
        sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_id", "event_id", name="uq_uber_sandbox_event"),
    )
    for name in ("client_id", "store_id", "order_id", "estado"):
        op.create_index(f"ix_uber_sandbox_events_{name}", "uber_sandbox_events", [name])


def downgrade() -> None:
    # An application rollback must not erase receipt/deduplication evidence.
    pass
