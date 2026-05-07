"""Add loyalty reward redemption fields to sales.

Revision ID: c3d4e5f6a7b8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ventas") as batch_op:
        batch_op.add_column(
            sa.Column(
                "recompensa_lealtad_canjeada",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )
        batch_op.add_column(sa.Column("recompensa_lealtad_nombre", sa.String(120)))
        batch_op.add_column(
            sa.Column(
                "recompensa_lealtad_monto",
                sa.Numeric(14, 2),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("ventas") as batch_op:
        batch_op.drop_column("recompensa_lealtad_monto")
        batch_op.drop_column("recompensa_lealtad_nombre")
        batch_op.drop_column("recompensa_lealtad_canjeada")
