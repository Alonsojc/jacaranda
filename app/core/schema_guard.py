"""Small runtime schema guards for deployments that fall back to create_all."""

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, inspect, text
from sqlalchemy.engine import Engine

from app.models.compras import RecepcionOrdenCompra
from app.models.notificacion import FCMToken
from app.models.pago_online import ConektaWebhookEvent
from app.models.pedido import DetallePedido
from app.models.whatsapp import WhatsAppWebhookEvent


def _sql_type(engine: Engine, column_type) -> str:
    return column_type.compile(dialect=engine.dialect)


def _add_column_if_missing(
    conn,
    engine: Engine,
    table_name: str,
    existing_columns: set[str],
    column_name: str,
    column_type,
    *,
    server_default: str | None = None,
    nullable: bool = True,
) -> None:
    if column_name in existing_columns:
        return
    ddl = (
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} "
        f"{_sql_type(engine, column_type)}"
    )
    if server_default is not None:
        ddl += f" DEFAULT {server_default}"
    if not nullable:
        ddl += " NOT NULL"
    conn.execute(text(ddl))
    existing_columns.add(column_name)


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

        if "pedidos" in tables:
            pedido_columns = {col["name"] for col in inspector.get_columns("pedidos")}
            # Delivery/reserva fields were added after some production databases
            # already had a pedidos table. Missing mapped columns break all reads.
            for column_name, column_type, default, nullable in (
                ("cliente_id", Integer(), None, True),
                ("notas", Text(), None, True),
                ("notas_internas", Text(), None, True),
                ("pagado", Boolean(), "false", False),
                ("anticipo", Numeric(14, 2), "0", False),
                ("total", Numeric(14, 2), "0", False),
                ("repartidor_nombre", String(200), None, True),
                ("repartidor_telefono", String(20), None, True),
                ("direccion_entrega", Text(), None, True),
                ("referencia_entrega", String(300), None, True),
                ("costo_envio", Numeric(10, 2), "0", False),
                ("en_ruta_en", DateTime(timezone=True), None, True),
                ("entregado_en", DateTime(timezone=True), None, True),
                ("creado_en", DateTime(timezone=True), None, True),
                ("actualizado_en", DateTime(timezone=True), None, True),
            ):
                _add_column_if_missing(
                    conn,
                    engine,
                    "pedidos",
                    pedido_columns,
                    column_name,
                    column_type,
                    server_default=default,
                    nullable=nullable,
                )

    ConektaWebhookEvent.__table__.create(bind=engine, checkfirst=True)
    DetallePedido.__table__.create(bind=engine, checkfirst=True)
    RecepcionOrdenCompra.__table__.create(bind=engine, checkfirst=True)
    WhatsAppWebhookEvent.__table__.create(bind=engine, checkfirst=True)
    FCMToken.__table__.create(bind=engine, checkfirst=True)
