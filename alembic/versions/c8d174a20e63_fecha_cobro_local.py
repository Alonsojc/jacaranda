"""Preserve optional device collection time without rewriting any sale."""

from alembic import op
import sqlalchemy as sa

revision = "c8d174a20e63"
down_revision = "b3e71a09c442"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "ventas" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("ventas")}
        if "fecha_cobro_local" not in columns:
            op.add_column("ventas", sa.Column("fecha_cobro_local", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    # Preserve collection evidence when rolling back application code.
    pass
