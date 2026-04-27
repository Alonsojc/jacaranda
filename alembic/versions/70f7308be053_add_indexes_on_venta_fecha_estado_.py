"""add indexes on venta fecha estado cliente_id

Revision ID: 70f7308be053
Revises: 468f170cd373
Create Date: 2026-04-15 03:15:33.302840

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '70f7308be053'
down_revision: Union[str, Sequence[str], None] = '468f170cd373'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(table_name: str, index_name: str) -> bool:
    return index_name in {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    """Add performance indexes on ventas table."""
    # Indexes for frequently queried columns in reports and filters
    if not _index_exists('ventas', 'ix_ventas_fecha'):
        op.create_index('ix_ventas_fecha', 'ventas', ['fecha'])
    if not _index_exists('ventas', 'ix_ventas_estado'):
        op.create_index('ix_ventas_estado', 'ventas', ['estado'])
    if not _index_exists('ventas', 'ix_ventas_cliente_id'):
        op.create_index('ix_ventas_cliente_id', 'ventas', ['cliente_id'])


def downgrade() -> None:
    """Remove performance indexes."""
    op.drop_index('ix_ventas_cliente_id', table_name='ventas')
    op.drop_index('ix_ventas_estado', table_name='ventas')
    op.drop_index('ix_ventas_fecha', table_name='ventas')
