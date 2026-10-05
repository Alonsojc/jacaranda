"""Record cash custody and the float handed to the next shift.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "cortes_caja" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("cortes_caja")}
    with op.batch_alter_table("cortes_caja") as batch_op:
        if "fondo_entregado" not in columns:
            batch_op.add_column(sa.Column("fondo_entregado", sa.Numeric(14, 2), nullable=True))
        if "recibido_por" not in columns:
            batch_op.add_column(sa.Column("recibido_por", sa.String(150), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "cortes_caja" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("cortes_caja")}
    with op.batch_alter_table("cortes_caja") as batch_op:
        if "recibido_por" in columns:
            batch_op.drop_column("recibido_por")
        if "fondo_entregado" in columns:
            batch_op.drop_column("fondo_entregado")
