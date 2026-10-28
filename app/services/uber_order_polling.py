"""Bounded canonical GET checks; never sends an order command or touches the POS."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.uber_eats import UberSandboxEvent, UberSandboxOrder, UberSandboxOrderCheck
from app.services.uber_order_service import inspect_order
from app.services.uber_webhook_service import STORE_EVENT_TYPES, WebhookError, sandbox_identity

CHECK_INTERVAL_SECONDS = 30
LEASE_SECONDS = 120


def process_check(db: Session, *, now: datetime | None = None) -> bool:
    if not settings.UBER_EATS_SANDBOX_ORDER_POLLING_ENABLED:
        return False
    if not settings.UBER_EATS_SANDBOX_MANAGEMENT_ENABLED:
        raise WebhookError(409, "El seguimiento requiere la gestion privada de Sandbox.")
    client_id, store_id = sandbox_identity()
    now = now or datetime.now(timezone.utc)
    identity = {"client_id": client_id, "store_id": store_id}
    # Recover discovery after a restart without synthesizing or acknowledging webhooks.
    missing = db.query(UberSandboxEvent.order_id).filter_by(**identity).filter(
        UberSandboxEvent.event_type.not_in(STORE_EVENT_TYPES),
    ).outerjoin(UberSandboxOrderCheck, and_(
        UberSandboxOrderCheck.client_id == client_id, UberSandboxOrderCheck.store_id == store_id,
        UberSandboxOrderCheck.order_id == UberSandboxEvent.order_id,
    )).filter(UberSandboxOrderCheck.id.is_(None)).distinct().order_by(UberSandboxEvent.order_id).limit(100).all()
    for (order_id,) in missing:
        try:
            with db.begin_nested():
                db.add(UberSandboxOrderCheck(**identity, order_id=order_id, next_check_at=now))
                db.flush()
        except IntegrityError:
            pass
    db.commit()
    job = db.query(UberSandboxOrderCheck).filter_by(**identity).outerjoin(UberSandboxOrder, and_(
        UberSandboxOrder.client_id == client_id, UberSandboxOrder.store_id == store_id,
        UberSandboxOrder.order_id == UberSandboxOrderCheck.order_id,
    )).filter(
        UberSandboxOrderCheck.next_check_at <= now,
        or_(UberSandboxOrder.id.is_(None), UberSandboxOrder.state.not_in(("FAILED", "SUCCEEDED"))),
    ).order_by(UberSandboxOrderCheck.next_check_at, UberSandboxOrderCheck.id).first()
    if job is None:
        return False
    job_id, order_id = job.id, job.order_id
    lease = str(uuid4())
    claimed = db.execute(update(UberSandboxOrderCheck).where(
        UberSandboxOrderCheck.id == job_id, UberSandboxOrderCheck.next_check_at <= now,
    ).values(lease_key=lease, attempted_at=now, next_check_at=now + timedelta(seconds=LEASE_SECONDS))
        .execution_options(synchronize_session=False))
    db.commit()
    if claimed.rowcount != 1:
        return False
    event = db.query(UberSandboxEvent).filter_by(**identity, order_id=order_id).filter(
        UberSandboxEvent.event_type.not_in(STORE_EVENT_TYPES),
    ).order_by(UberSandboxEvent.event_time.desc(), UberSandboxEvent.id.desc()).first()
    error = None
    try:
        inspect_order(db, UUID(event.event_id), background=True)
    except WebhookError as exc:
        db.rollback()
        error = getattr(exc, "provider_status", None) or exc.status_code
    # Only this lease may reschedule the next GET. Failed attempts survive a restart.
    job = db.query(UberSandboxOrderCheck).populate_existing().filter_by(id=job_id).one()
    failures = min(job.failures + 1, 10) if error else 0
    delay = (3600 if error == 404 else min(3600, 30 * 2 ** failures)) if error else CHECK_INTERVAL_SECONDS
    values = {
        "lease_key": None, "failures": failures, "last_error": error,
        "next_check_at": now + timedelta(seconds=delay),
    }
    if error:
        values["needs_review"] = True
    else:
        values["checked_at"] = now
    db.execute(update(UberSandboxOrderCheck).where(
        UberSandboxOrderCheck.id == job_id, UberSandboxOrderCheck.lease_key == lease,
    ).values(**values).execution_options(synchronize_session=False))
    db.commit()
    return True
