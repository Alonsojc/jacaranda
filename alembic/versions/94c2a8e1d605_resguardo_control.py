"""Add an uninitialized resguardo checkpoint and safe expense retry keys."""

from alembic import op
import sqlalchemy as sa

revision = "94c2a8e1d605"
down_revision = "83d9a71bc502"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "resguardo_control" not in tables:
        op.create_table(
            "resguardo_control",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("saldo_inicial", sa.Numeric(14, 2), nullable=False),
            sa.Column("ultimo_corte_id", sa.Integer(), nullable=False),
            sa.Column("ultimo_egreso_id", sa.Integer(), nullable=False),
            sa.Column("creado_por_id", sa.Integer(), nullable=False),
            sa.Column("iniciado_en", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("id = 1", name="ck_resguardo_singleton"),
            sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
        )
    if "egresos" in tables:
        columns = {c["name"] for c in inspector.get_columns("egresos")}
        for name, size in (("idempotency_key", 80), ("request_fingerprint", 64)):
            if name not in columns:
                op.add_column("egresos", sa.Column(name, sa.String(size), nullable=True))
        indexes = {i["name"] for i in inspector.get_indexes("egresos")}
        if "ix_egresos_idempotency_key" not in indexes:
            op.create_index("ix_egresos_idempotency_key", "egresos", ["idempotency_key"], unique=True)


def downgrade() -> None:
    # Retain the opening balance and retry identities; an app rollback must not erase cash history.
    pass
