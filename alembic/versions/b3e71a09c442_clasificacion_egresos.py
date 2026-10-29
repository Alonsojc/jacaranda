"""Add an optional expense classification without rewriting historical data."""

from alembic import op
import sqlalchemy as sa

revision = "b3e71a09c442"
down_revision = "a6d8e102c739"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "egresos" not in inspector.get_table_names():
        return
    if "clasificacion" not in {column["name"] for column in inspector.get_columns("egresos")}:
        op.add_column("egresos", sa.Column(
            "clasificacion", sa.String(12),
            sa.CheckConstraint("clasificacion IS NULL OR clasificacion IN ('costo', 'gasto')", name="ck_egresos_clasificacion"),
            nullable=True,
        ))


def downgrade():
    # Keep recorded classifications on application rollback.
    pass
