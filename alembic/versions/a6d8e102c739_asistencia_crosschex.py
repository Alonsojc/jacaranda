"""Add independent clock evidence; leave existing payroll and sales unchanged."""

from alembic import op
import sqlalchemy as sa

revision = "a6d8e102c739"
down_revision = "94c2a8e1d605"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "asistencia_checadas" not in tables:
        op.create_table(
            "asistencia_checadas",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("identidad", sa.String(64), nullable=False, unique=True),
            sa.Column("cuenta", sa.String(140), nullable=False),
            sa.Column("numero_reloj", sa.String(80), nullable=False),
            sa.Column("nombre_reloj", sa.String(201), nullable=False),
            sa.Column("fecha", sa.DateTime(timezone=True), nullable=False),
            sa.Column("tipo_original", sa.Integer(), nullable=False),
            sa.Column("dispositivo", sa.String(80), nullable=False),
            sa.Column("dispositivo_nombre", sa.String(100), nullable=False),
            sa.Column("importado_en", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_asistencia_cuenta_fecha", "asistencia_checadas", ["cuenta", "fecha"])
    if "asistencia_vinculos" not in tables:
        op.create_table(
            "asistencia_vinculos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cuenta", sa.String(140), nullable=False),
            sa.Column("numero_reloj", sa.String(80), nullable=False),
            sa.Column("empleado_id", sa.Integer(), sa.ForeignKey("empleados.id"), nullable=False),
            sa.Column("creado_por_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("cuenta", "numero_reloj", name="uq_asistencia_reloj"),
            sa.UniqueConstraint("cuenta", "empleado_id", name="uq_asistencia_empleado"),
        )
    if "asistencia_sincronizaciones" not in tables:
        op.create_table(
            "asistencia_sincronizaciones",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cuenta", sa.String(140), nullable=False),
            sa.Column("desde", sa.DateTime(timezone=True), nullable=False),
            sa.Column("hasta", sa.DateTime(timezone=True), nullable=False),
            sa.Column("nuevas", sa.Integer(), nullable=False),
            sa.Column("repetidas", sa.Integer(), nullable=False),
            sa.Column("omitidas_otro_equipo", sa.Integer(), nullable=False),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("completada_en", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_asistencia_sync_cuenta", "asistencia_sincronizaciones", ["cuenta", "id"])


def downgrade():
    # Retain evidence on application rollback; no payroll or sales tables changed.
    pass
