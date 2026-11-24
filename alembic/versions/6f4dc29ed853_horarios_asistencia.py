"""Add a staff schedule without changing clock or payroll data."""

import sqlalchemy as sa
from alembic import op

revision = "6f4dc29ed853"
down_revision = "c8d174a20e63"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "asistencia_personas_horario" not in tables:
        op.create_table(
            "asistencia_personas_horario",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nombre", sa.String(100), nullable=False),
            sa.Column("nombre_normalizado", sa.String(300), nullable=False, unique=True),
            sa.Column("cuenta_reloj", sa.String(140), nullable=True),
            sa.Column("numero_reloj", sa.String(80), nullable=True),
            sa.UniqueConstraint("cuenta_reloj", "numero_reloj", name="uq_asistencia_horario_reloj"),
        )
    if "asistencia_horarios_semanales" not in tables:
        op.create_table(
            "asistencia_horarios_semanales",
            sa.Column("persona_id", sa.Integer(), sa.ForeignKey("asistencia_personas_horario.id"), primary_key=True),
            sa.Column("vigente_desde", sa.Date(), primary_key=True),
            sa.Column("dias", sa.JSON(), nullable=False),
            sa.Column("modalidad", sa.String(20), nullable=False),
            sa.Column("nota", sa.String(300), nullable=False),
        )
    if "asistencia_turnos_fecha" not in tables:
        op.create_table(
            "asistencia_turnos_fecha",
            sa.Column("persona_id", sa.Integer(), sa.ForeignKey("asistencia_personas_horario.id"), primary_key=True),
            sa.Column("fecha", sa.Date(), primary_key=True),
            sa.Column("tipo", sa.String(20), nullable=False),
            sa.Column("horas", sa.JSON(none_as_null=True), nullable=True),
            sa.Column("modalidad", sa.String(20), nullable=False),
            sa.Column("nota", sa.String(300), nullable=False),
        )
        op.create_index("ix_asistencia_turnos_fecha", "asistencia_turnos_fecha", ["fecha"])


def downgrade():
    # The previous application can run with these tables present.
    pass
