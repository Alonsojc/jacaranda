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


def _ensure_postgres_enum_values(engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text(
                "ALTER TYPE estadopedido ADD VALUE IF NOT EXISTS 'EN_RUTA'"
            ))
    except Exception:
        # The enum may not exist on SQLite-created or manually shaped schemas.
        return


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_count(conn, table_name: str) -> int:
    try:
        return int(
            conn.execute(text(f"SELECT COUNT(*) FROM {_quote_ident(table_name)}")).scalar()
            or 0
        )
    except Exception:
        return 0


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


def _relax_not_nulls(
    conn,
    engine: Engine,
    table_name: str,
    *,
    required_columns: set[str],
) -> None:
    if engine.dialect.name == "sqlite":
        return
    inspector = inspect(conn)
    for column in inspector.get_columns(table_name):
        column_name = column["name"]
        if column_name in required_columns or column.get("nullable", True):
            continue
        conn.execute(text(
            f"ALTER TABLE {_quote_ident(table_name)} "
            f"ALTER COLUMN {_quote_ident(column_name)} DROP NOT NULL"
        ))


def _normalize_detalle_types_postgres(conn, engine: Engine) -> None:
    if engine.dialect.name != "postgresql":
        return
    columns = {col["name"] for col in inspect(conn).get_columns("detalles_pedido")}
    casts = {
        "pedido_id": (
            "INTEGER",
            "CASE WHEN {c}::text ~ '^\\d+$' THEN {c}::integer ELSE NULL END",
        ),
        "producto_id": (
            "INTEGER",
            "CASE WHEN {c} IS NULL OR {c}::text = '' THEN NULL "
            "WHEN {c}::text ~ '^\\d+$' THEN {c}::integer ELSE NULL END",
        ),
        "cantidad": (
            "INTEGER",
            "CASE WHEN {c}::text ~ '^\\d+$' THEN {c}::integer ELSE 1 END",
        ),
        "precio_unitario": (
            "NUMERIC(12, 2)",
            "CASE WHEN {c}::text ~ '^-?\\d+(\\.\\d+)?$' THEN {c}::numeric ELSE 0 END",
        ),
    }
    for column_name, (target_type, expression) in casts.items():
        if column_name not in columns:
            continue
        quoted = _quote_ident(column_name)
        conn.execute(text(
            f"ALTER TABLE {_quote_ident('detalles_pedido')} "
            f"ALTER COLUMN {quoted} TYPE {target_type} "
            f"USING {expression.format(c=quoted)}"
        ))


def ensure_runtime_schema(engine: Engine) -> None:
    """
    Ensure additive safety columns/tables exist when Alembic cannot run.

    Existing deployments have historically fallen back to Base.metadata.create_all,
    which creates missing tables but does not add new columns to existing tables.
    Keep this guard narrow and additive only.
    """
    _ensure_postgres_enum_values(engine)
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

    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        if (
            "pedidos" in tables
            and "detalles_pedido" in tables
            and _table_count(conn, "pedidos") == 0
            and _table_count(conn, "detalles_pedido") == 0
        ):
            # If an empty legacy details table has the wrong shape, the safest
            # repair is to recreate it before the app starts accepting orders.
            conn.execute(text("DROP TABLE detalles_pedido"))

    ConektaWebhookEvent.__table__.create(bind=engine, checkfirst=True)
    DetallePedido.__table__.create(bind=engine, checkfirst=True)
    RecepcionOrdenCompra.__table__.create(bind=engine, checkfirst=True)
    WhatsAppWebhookEvent.__table__.create(bind=engine, checkfirst=True)
    FCMToken.__table__.create(bind=engine, checkfirst=True)

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        if "detalles_pedido" in tables:
            detalle_columns = {
                col["name"] for col in inspector.get_columns("detalles_pedido")
            }
            for column_name, column_type, default, nullable in (
                ("pedido_id", Integer(), None, True),
                ("producto_id", Integer(), None, True),
                ("descripcion", String(300), "''", False),
                ("cantidad", Integer(), "1", False),
                ("precio_unitario", Numeric(12, 2), "0", False),
                ("notas", Text(), None, True),
            ):
                _add_column_if_missing(
                    conn,
                    engine,
                    "detalles_pedido",
                    detalle_columns,
                    column_name,
                    column_type,
                    server_default=default,
                    nullable=nullable,
                )
            _normalize_detalle_types_postgres(conn, engine)
            _relax_not_nulls(
                conn,
                engine,
                "detalles_pedido",
                required_columns={
                    "id",
                    "pedido_id",
                    "descripcion",
                    "cantidad",
                    "precio_unitario",
                },
            )

        if "pedidos" in tables:
            _relax_not_nulls(
                conn,
                engine,
                "pedidos",
                required_columns={
                    "id",
                    "folio",
                    "cliente_nombre",
                    "fecha_entrega",
                    "estado",
                    "origen",
                },
            )
