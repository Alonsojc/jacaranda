"""Configuración de base de datos SQLAlchemy (SQLite / PostgreSQL)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings

_connect_args = {}
_engine_options = {
    "connect_args": _connect_args,
    "echo": settings.DEBUG,
    "pool_pre_ping": True,
}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
else:
    _engine_options.update(
        {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_recycle": settings.DB_POOL_RECYCLE_SECONDS,
        }
    )

engine = create_engine(settings.DATABASE_URL, **_engine_options)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency para obtener sesión de base de datos."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
