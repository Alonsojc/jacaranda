"""Add product packaging ingredient links.

Revision ID: b9c0d1e2f3a4
Revises: a5b6c7d8e9f0
Create Date: 2026-05-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, Sequence[str], None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("productos") as batch_op:
        batch_op.add_column(sa.Column("caja_ingrediente_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "caja_cantidad",
                sa.Numeric(12, 4),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.create_foreign_key(
            "fk_productos_caja_ingrediente_id_ingredientes",
            "ingredientes",
            ["caja_ingrediente_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("productos") as batch_op:
        batch_op.drop_constraint(
            "fk_productos_caja_ingrediente_id_ingredientes",
            type_="foreignkey",
        )
        batch_op.drop_column("caja_cantidad")
        batch_op.drop_column("caja_ingrediente_id")
