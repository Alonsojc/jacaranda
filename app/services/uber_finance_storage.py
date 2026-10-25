"""Private POS schema in the existing TEST database, never the production DB."""

import os
from decimal import Decimal

from sqlalchemy import create_engine, func, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import Base
from app.models.inventario import Ingrediente, Producto, UnidadMedida
from app.models.usuario import RolUsuario, Usuario
from app.services.uber_pos_sandbox_service import RehearsalError, TEST_CLIENT_ID, TEST_STORE_ID


SCHEMA = "uber_finance_test"
TABLES = frozenset({
    "categorias_producto", "clientes", "detalles_venta", "familias_producto", "ingredientes",
    "log_auditoria", "lotes_ingrediente", "movimientos_inventario", "pagos_venta", "productos",
    "proveedores", "usuarios", "ventas",
})
PRODUCTS = {
    "jacaranda-sandbox-brownie": ("UBER-TEST-BROWNIE", "Brownie ficticio"),
    "jacaranda-sandbox-galleta": ("UBER-TEST-COOKIE", "Galleta ficticia"),
}
OPERATOR = "sandbox-finance@example.invalid"
_engine = None
_sessions = None


def validate_configuration():
    expected_host = os.environ.get("JACARANDA_SANDBOX_DATABASE_HOST", "")
    try:
        url = make_url(settings.DATABASE_URL)
    except Exception:
        raise RehearsalError("Configuracion financiera Sandbox no valida.") from None
    if not (
        os.environ.get("JACARANDA_RUNTIME") == os.environ.get("RAILWAY_ENVIRONMENT_NAME") == "uber-sandbox"
        and settings.UBER_EATS_SANDBOX_FINANCE_ENABLED and settings.UBER_EATS_SANDBOX_MANAGEMENT_ENABLED
        and settings.UBER_EATS_SANDBOX_ENABLED
        and settings.UBER_EATS_SANDBOX_CLIENT_ID == TEST_CLIENT_ID
        and settings.UBER_EATS_SANDBOX_STORE_ID == TEST_STORE_ID
        and url.drivername == "postgresql" and url.host == expected_host
        and expected_host.endswith(".railway.internal") and not url.query
        and url.database == "jacaranda_uber_sandbox" and url.username == "jacaranda_sandbox"
    ):
        raise RehearsalError("Finanzas solo permite la base privada de Jacaranda Sandbox.")
    return url


def validate_session(db: Session):
    expected = validate_configuration()
    engine = db.get_bind().engine
    mapping = engine.get_execution_options().get("schema_translate_map", {})
    # SQLAlchemy adds its internal _none entry after compiling a mapped statement.
    if (engine.url != expected or mapping.get(None) != SCHEMA or set(mapping) - {None, "_none"}
            or ("_none" in mapping and mapping["_none"] != SCHEMA)):
        raise RehearsalError("El enlace financiero requiere su esquema TEST exclusivo.")
    for mapper in Base.registry.mappers:
        if db.get_bind(mapper=mapper).engine is not engine:
            raise RehearsalError("No se permiten conexiones alternas en el ensayo.")
    with db.no_autoflush:
        schema = db.execute(func.current_schema().select()).scalar()
        search = db.execute(func.current_schemas(False).select()).scalar()
        actual = db.execute(text("SELECT current_database(), current_user")).one()
    if schema != SCHEMA or list(search) != [SCHEMA] or tuple(actual) != (expected.database, expected.username):
        raise RehearsalError("La conexion no confirma el aislamiento financiero TEST.")


def initialize():
    global _engine, _sessions
    url = validate_configuration()
    if _engine is not None:
        return
    engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=1,
                           connect_args={"options": "-csearch_path=" + SCHEMA},
                           execution_options={"schema_translate_map": {None: SCHEMA}})
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA IF NOT EXISTS uber_finance_test"))
            connection.execute(text("REVOKE ALL ON SCHEMA uber_finance_test FROM PUBLIC"))
            present = set(inspect(connection).get_table_names(schema=SCHEMA))
            if present - TABLES:
                raise RehearsalError("El esquema financiero contiene tablas no autorizadas.")
            Base.metadata.create_all(connection, tables=[Base.metadata.tables[name] for name in TABLES])
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        with sessions() as db:
            validate_session(db)
            seed(db)
        _engine, _sessions = engine, sessions
    except Exception:
        engine.dispose()
        raise


def seed(db: Session):
    """Create fixtures once; never reset an existing stock balance on restart."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(func.pg_advisory_xact_lock(211025, 1).select())
    operator = db.query(Usuario).filter_by(email=OPERATOR).first()
    if operator is None:
        operator = Usuario(nombre="Operador Sandbox", email=OPERATOR, hashed_password="not-a-login-credential",
                           rol=RolUsuario.ADMINISTRADOR)
        db.add(operator)
    box = db.query(Ingrediente).filter_by(nombre="Empaque ficticio Uber TEST").first()
    if box is None:
        box = Ingrediente(nombre="Empaque ficticio Uber TEST", unidad_medida=UnidadMedida.CAJA,
                          es_empaque=True, stock_actual=Decimal(200), costo_unitario=Decimal(1))
        db.add(box)
        db.flush()
    for code, name in PRODUCTS.values():
        if db.query(Producto.id).filter_by(codigo=code).first() is None:
            db.add(Producto(codigo=code, nombre=name, precio_unitario=Decimal(99), precio_uber_eats=Decimal(88),
                            stock_actual=Decimal(100), caja_ingrediente_id=box.id, caja_cantidad=Decimal(1)))
    db.commit()


def bindings(db: Session):
    operator = db.query(Usuario).filter_by(email=OPERATOR, activo=True, rol=RolUsuario.ADMINISTRADOR).one()
    mapping = {item: db.query(Producto.id).filter_by(codigo=code, activo=True).one()[0]
               for item, (code, _) in PRODUCTS.items()}
    return operator.id, mapping


def get_db():
    validate_configuration()
    if _sessions is None:
        raise RehearsalError("El almacenamiento financiero de pruebas no esta listo.")
    with _sessions() as db:
        validate_session(db)
        yield db


def shutdown():
    global _engine, _sessions
    if _engine is not None:
        _engine.dispose()
    _engine, _sessions = None, None
