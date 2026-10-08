"""Add delivery dates and payment retry keys without rewriting history."""

from alembic import op
import sqlalchemy as sa

revision = "83d9a71bc502"
down_revision = "7d91c0a64e28"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "cafeteria_ventas" in tables:
        columns = {c["name"] for c in inspector.get_columns("cafeteria_ventas")}
        if "fecha_entrega" not in columns:
            op.add_column("cafeteria_ventas", sa.Column("fecha_entrega", sa.Date(), nullable=True))
    if "pagos_cafeteria_venta" in tables:
        columns = {c["name"] for c in inspector.get_columns("pagos_cafeteria_venta")}
        if "idempotency_key" not in columns:
            op.add_column("pagos_cafeteria_venta", sa.Column("idempotency_key", sa.String(80), nullable=True))
        indexes = {i["name"] for i in inspector.get_indexes("pagos_cafeteria_venta")}
        if "ix_pagos_cafeteria_venta_idempotency_key" not in indexes:
            op.create_index("ix_pagos_cafeteria_venta_idempotency_key", "pagos_cafeteria_venta", ["idempotency_key"], unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "pagos_cafeteria_venta" in tables:
        indexes = {i["name"] for i in inspector.get_indexes("pagos_cafeteria_venta")}
        if "ix_pagos_cafeteria_venta_idempotency_key" in indexes:
            op.drop_index("ix_pagos_cafeteria_venta_idempotency_key", table_name="pagos_cafeteria_venta")
        if "idempotency_key" in {c["name"] for c in inspector.get_columns("pagos_cafeteria_venta")}:
            with op.batch_alter_table("pagos_cafeteria_venta") as batch:
                batch.drop_column("idempotency_key")
    if "cafeteria_ventas" in tables:
        if "fecha_entrega" in {c["name"] for c in inspector.get_columns("cafeteria_ventas")}:
            with op.batch_alter_table("cafeteria_ventas") as batch:
                batch.drop_column("fecha_entrega")
