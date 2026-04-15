"""
Funciones de compatibilidad entre SQLite y PostgreSQL.
Permite que las queries con funciones de fecha funcionen en ambos motores.
"""

from sqlalchemy import func, cast, Date, extract

from app.core.config import settings


def _is_sqlite() -> bool:
    return settings.DATABASE_URL.startswith("sqlite")


def db_extract_hour(col):
    """Extrae la hora (0-23) de una columna datetime."""
    if _is_sqlite():
        return func.strftime("%H", col)
    return extract("hour", col)


def db_extract_dow(col):
    """Extrae día de la semana (0=domingo, 6=sábado) de una columna datetime."""
    if _is_sqlite():
        return func.strftime("%w", col)
    return extract("dow", col)


def db_cast_date(col):
    """Extrae solo la fecha de una columna datetime."""
    if _is_sqlite():
        return func.date(col)
    return cast(col, Date)
