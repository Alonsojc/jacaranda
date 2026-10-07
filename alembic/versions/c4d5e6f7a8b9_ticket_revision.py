"""Track completed ticket corrections without replacing the original sale."""

from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ventas" not in inspector.get_table_names():
        return
    if "edicion_revision" not in {c["name"] for c in inspector.get_columns("ventas")}:
        op.add_column("ventas", sa.Column("edicion_revision", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ventas" in inspector.get_table_names():
        if "edicion_revision" in {c["name"] for c in inspector.get_columns("ventas")}:
            with op.batch_alter_table("ventas") as batch:
                batch.drop_column("edicion_revision")
