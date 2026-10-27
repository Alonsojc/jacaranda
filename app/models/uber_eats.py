"""Recepcion durable y aislada de eventos Uber Eats de pruebas."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

PENDING_ORDER_ACTION_STATES = ("enviando", "incierta", "pendiente_aviso")


class UberSandboxEvent(Base):
    __tablename__ = "uber_sandbox_events"
    __table_args__ = (UniqueConstraint("client_id", "event_id", name="uq_uber_sandbox_event"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(160), index=True)
    store_id: Mapped[str] = mapped_column(String(36), index=True)
    event_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(80))
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    event_time: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    estado: Mapped[str] = mapped_column(String(30), default="recibido", index=True)
    recibido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class UberSandboxOrder(Base):
    __tablename__ = "uber_sandbox_orders"
    __table_args__ = (UniqueConstraint("client_id", "store_id", "order_id", name="uq_uber_sandbox_order"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(160))
    store_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(40))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    pending_request_key: Mapped[str | None] = mapped_column(String(36))
    snapshot_json: Mapped[str] = mapped_column(Text)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UberSandboxAction(Base):
    __tablename__ = "uber_sandbox_actions"
    __table_args__ = (UniqueConstraint("client_id", "store_id", "request_key", name="uq_uber_sandbox_action"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(160))
    store_id: Mapped[str] = mapped_column(String(36))
    order_id: Mapped[str] = mapped_column(String(36), index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    fingerprint: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(20))
    estado: Mapped[str] = mapped_column(String(20))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UberSandboxStore(Base):
    __tablename__ = "uber_sandbox_stores"
    __table_args__ = (UniqueConstraint("client_id", "store_id", name="uq_uber_sandbox_store"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(160))
    store_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    lifecycle_event_time: Mapped[int] = mapped_column(Integer, default=0)
    integration_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    online_status: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    menu_json: Mapped[str] = mapped_column(Text, default="")
    menu_uploaded: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_request_key: Mapped[str | None] = mapped_column(String(36))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64))
    oauth_state_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    merchant_token_encrypted: Mapped[str | None] = mapped_column(Text)
    merchant_token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UberSandboxStoreAction(Base):
    __tablename__ = "uber_sandbox_store_actions"
    __table_args__ = (UniqueConstraint("client_id", "store_id", "request_key", name="uq_uber_store_action"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(160))
    store_id: Mapped[str] = mapped_column(String(36))
    request_key: Mapped[str] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20))
    desired_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UberSandboxStoreJob(Base):
    __tablename__ = "uber_sandbox_store_jobs"
    __table_args__ = (UniqueConstraint("client_id", "event_id", name="uq_uber_store_job"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(160))
    store_id: Mapped[str] = mapped_column(String(36))
    event_id: Mapped[str] = mapped_column(String(36))
    needs_menu: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
