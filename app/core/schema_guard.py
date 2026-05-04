"""Small runtime schema guards for deployments that fall back to create_all."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.models.compras import RecepcionOrdenCompra
from app.models.pago_online import ConektaWebhookEvent
from app.models.whatsapp import WhatsAppWebhookEvent


def ensure_runtime_schema(engine: Engine) -> None:
    """
    Ensure additive safety columns/tables exist when Alembic cannot run.

    Existing deployments have historically fallen back to Base.metadata.create_all,
    which creates missing tables but does not add new columns to existing tables.
    Keep this guard narrow and additive only.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table_name, index_name in (
            ("ventas", "ix_ventas_idempotency_key"),
            ("pedidos", "ix_pedidos_idempotency_key"),
        ):
            if table_name not in tables:
                continue
            columns = {col["name"] for col in inspector.get_columns(table_name)}
            if "idempotency_key" not in columns:
                conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN idempotency_key VARCHAR(80)"
                ))
            conn.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                f"ON {table_name} (idempotency_key)"
            ))

    ConektaWebhookEvent.__table__.create(bind=engine, checkfirst=True)
    RecepcionOrdenCompra.__table__.create(bind=engine, checkfirst=True)
    WhatsAppWebhookEvent.__table__.create(bind=engine, checkfirst=True)
