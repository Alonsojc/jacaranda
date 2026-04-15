"""add indexes on venta fecha estado cliente_id

Revision ID: 70f7308be053
Revises: 468f170cd373
Create Date: 2026-04-15 03:15:33.302840

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '70f7308be053'
down_revision: Union[str, Sequence[str], None] = '468f170cd373'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add performance indexes on ventas table."""
    # Indexes for frequently queried columns in reports and filters
    op.create_index('ix_ventas_fecha', 'ventas', ['fecha'])
    op.create_index('ix_ventas_estado', 'ventas', ['estado'])
    op.create_index('ix_ventas_cliente_id', 'ventas', ['cliente_id'])


def downgrade() -> None:
    """Remove performance indexes."""
    op.drop_index('ix_ventas_cliente_id', table_name='ventas')
    op.drop_index('ix_ventas_estado', table_name='ventas')
    op.drop_index('ix_ventas_fecha', table_name='ventas')
