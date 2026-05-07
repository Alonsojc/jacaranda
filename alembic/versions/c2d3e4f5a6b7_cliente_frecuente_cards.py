"""Add cliente frecuente card fields.

Revision ID: c2d3e4f5a6b7
Revises: b9c0d1e2f3a4
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, Sequence[str], None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("clientes") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cliente_frecuente",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "monto_lealtad_acumulado",
                sa.Numeric(14, 2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "recompensas_lealtad_canjeadas",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_index("ix_clientes_tarjeta_qr", ["tarjeta_qr"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("clientes") as batch_op:
        batch_op.drop_index("ix_clientes_tarjeta_qr")
        batch_op.drop_column("recompensas_lealtad_canjeadas")
        batch_op.drop_column("monto_lealtad_acumulado")
        batch_op.drop_column("cliente_frecuente")
