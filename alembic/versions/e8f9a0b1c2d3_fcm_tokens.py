"""fcm notification tokens

Revision ID: e8f9a0b1c2d3
Revises: d4e5f6a7b8c9
Create Date: 2026-05-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in inspect(op.get_bind()).get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return index_name in {
        index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)
    }


def upgrade() -> None:
    if not _table_exists("fcm_tokens"):
        op.create_table(
            "fcm_tokens",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("usuario_id", sa.Integer(), nullable=False),
            sa.Column("token", sa.Text(), nullable=False),
            sa.Column("plataforma", sa.String(length=80), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("activo", sa.Boolean(), nullable=False),
            sa.Column("ultimo_error", sa.Text(), nullable=True),
            sa.Column("registrado_en", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ultimo_envio_en", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token", name="uq_fcm_tokens_token"),
        )
    if not _index_exists("fcm_tokens", "ix_fcm_tokens_usuario_id"):
        op.create_index("ix_fcm_tokens_usuario_id", "fcm_tokens", ["usuario_id"])
    if not _index_exists("fcm_tokens", "ix_fcm_tokens_activo"):
        op.create_index("ix_fcm_tokens_activo", "fcm_tokens", ["activo"])


def downgrade() -> None:
    if _table_exists("fcm_tokens"):
        if _index_exists("fcm_tokens", "ix_fcm_tokens_activo"):
            op.drop_index("ix_fcm_tokens_activo", table_name="fcm_tokens")
        if _index_exists("fcm_tokens", "ix_fcm_tokens_usuario_id"):
            op.drop_index("ix_fcm_tokens_usuario_id", table_name="fcm_tokens")
        op.drop_table("fcm_tokens")
