"""editable loyalty configuration

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-05-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if not _table_exists("lealtad_configuracion"):
        op.create_table(
            "lealtad_configuracion",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "recompensa_monto_meta",
                sa.Numeric(12, 2),
                nullable=False,
                server_default="10000",
            ),
            sa.Column(
                "recompensa_nombre",
                sa.String(length=120),
                nullable=False,
                server_default="Pastel chico gratis",
            ),
            sa.Column(
                "puntos_por_peso",
                sa.Numeric(12, 4),
                nullable=False,
                server_default="0.1000",
            ),
            sa.Column(
                "valor_punto",
                sa.Numeric(12, 2),
                nullable=False,
                server_default="0.50",
            ),
            sa.Column(
                "cumpleanos_promo_activa",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "cumpleanos_descuento_porcentaje",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="10",
            ),
            sa.Column("puntos_expiran_dias", sa.Integer(), nullable=True),
            sa.Column(
                "actualizado_en",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute(
        """
        INSERT INTO lealtad_configuracion (
            id,
            recompensa_monto_meta,
            recompensa_nombre,
            puntos_por_peso,
            valor_punto,
            cumpleanos_promo_activa,
            cumpleanos_descuento_porcentaje,
            puntos_expiran_dias,
            actualizado_en
        )
        SELECT 1, 10000, 'Pastel chico gratis', 0.1000, 0.50, true, 10, NULL, CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM lealtad_configuracion WHERE id = 1
        )
        """
    )


def downgrade() -> None:
    if _table_exists("lealtad_configuracion"):
        op.drop_table("lealtad_configuracion")
