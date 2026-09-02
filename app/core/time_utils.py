"""Operational clock helpers.

Database timestamps stay in UTC. Calendar dates shown to staff and daily
business ranges use the configured operation timezone.
"""

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


DEFAULT_OPERATION_TIMEZONE = "America/Mexico_City"


def operation_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.APP_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_OPERATION_TIMEZONE)


def operation_now() -> datetime:
    return datetime.now(operation_timezone())


def operation_today() -> date:
    return operation_now().date()


def operation_datetime(value: datetime) -> datetime:
    """Convert a stored timestamp to local operation time.

    SQLite drops timezone metadata, while Jacaranda stores those values in
    UTC. Treat naive database values as UTC before converting them.
    """

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(operation_timezone())


def normalize_database_datetime(value: datetime) -> datetime:
    """Convert an aware datetime to the representation used by the database."""

    value_utc = value.astimezone(timezone.utc)
    if settings.DATABASE_URL.startswith("sqlite"):
        return value_utc.replace(tzinfo=None)
    return value_utc


def operation_period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    zone = operation_timezone()
    return (
        normalize_database_datetime(datetime.combine(start, time.min, tzinfo=zone)),
        normalize_database_datetime(datetime.combine(end, time.max, tzinfo=zone)),
    )


def operation_day_bounds(day: date) -> tuple[datetime, datetime]:
    return operation_period_bounds(day, day)
