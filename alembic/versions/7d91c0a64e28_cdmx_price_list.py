"""Add an independent CDMX price without changing stock or existing receipts."""

from alembic import op
import sqlalchemy as sa

revision = "7d91c0a64e28"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "productos" not in inspector.get_table_names():
        return
    if "precio_cdmx" not in {c["name"] for c in inspector.get_columns("productos")}:
        op.add_column("productos", sa.Column("precio_cdmx", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "productos" in inspector.get_table_names():
        if "precio_cdmx" in {c["name"] for c in inspector.get_columns("productos")}:
            with op.batch_alter_table("productos") as batch:
                batch.drop_column("precio_cdmx")
