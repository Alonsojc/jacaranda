"""egresos operativos

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-05-06 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
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
    if not _table_exists("egresos"):
        op.create_table(
            "egresos",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("concepto", sa.String(length=200), nullable=False),
            sa.Column("monto", sa.Numeric(14, 2), nullable=False),
            sa.Column("categoria", sa.String(length=60), nullable=False),
            sa.Column("metodo_pago", sa.String(length=30), nullable=False),
            sa.Column("fecha", sa.Date(), nullable=False),
            sa.Column("proveedor", sa.String(length=150), nullable=True),
            sa.Column("notas", sa.Text(), nullable=True),
            sa.Column("activo", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("creado_por_id", sa.Integer(), nullable=True),
            sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["creado_por_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    for index_name, columns in {
        "ix_egresos_concepto": ["concepto"],
        "ix_egresos_categoria": ["categoria"],
        "ix_egresos_metodo_pago": ["metodo_pago"],
        "ix_egresos_fecha": ["fecha"],
        "ix_egresos_activo": ["activo"],
    }.items():
        if not _index_exists("egresos", index_name):
            op.create_index(index_name, "egresos", columns)


def downgrade() -> None:
    if _table_exists("egresos"):
        for index_name in [
            "ix_egresos_activo",
            "ix_egresos_fecha",
            "ix_egresos_metodo_pago",
            "ix_egresos_categoria",
            "ix_egresos_concepto",
        ]:
            if _index_exists("egresos", index_name):
                op.drop_index(index_name, table_name="egresos")
        op.drop_table("egresos")
