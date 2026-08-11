import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, List, Any, Dict
from sqlalchemy import String, DateTime, ForeignKey, Boolean, Integer, JSON, Numeric, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.app.core.database import Base

# Postgres-native JSONB with graceful fallback to standard JSON for SQLite unit tests
JSON_TYPE = JSONB().with_variant(JSON, "sqlite")
UUID_TYPE = PG_UUID(as_uuid=True)

def utc_now() -> datetime:
    """Helper utility for generating timezone-aware UTC timestamps."""
    return datetime.now(timezone.utc)

class Tenant(Base):
    """
    Represents an enterprise tenant (organization/team) using the LLM Gateway.
    
    Uses PostgreSQL JSONB for binary JSON storage, allowing fast GIN-indexed queries on metadata.
    """
    __tablename__ = "tenants"
    __table_args__ = (
        Index("ix_tenants_name_active", "name", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    metadata_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    api_keys: Mapped[List["APIKey"]] = relationship("APIKey", back_populates="tenant", cascade="all, delete-orphan")
    analytics_events: Mapped[List["AnalyticsEvent"]] = relationship("AnalyticsEvent", back_populates="tenant", cascade="all, delete-orphan")


class APIKey(Base):
    """
    Hashed authentication keys bound to a specific Tenant.
    """
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_tenant_active_created", "tenant_id", "is_active", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="api_keys")


class ModelPricing(Base):
    """
    Point-in-time token pricing reference repository for cost computation.
    """
    __tablename__ = "model_pricing"
    __table_args__ = (
        UniqueConstraint("provider", "model", "active_from", name="uq_model_pricing_provider_model_active_from"),
        Index("ix_model_pricing_lookup", "provider", "model", "active_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    input_token_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)   # Rate per 1k tokens ($)
    output_token_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)  # Rate per 1k tokens ($)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)


class AnalyticsEvent(Base):
    """
    High-throughput execution logs for every LLM Gateway transaction.
    
    Uses PostgreSQL JSONB (`metadata_payload`) for high-performance JSON queries and zero-downtime extensibility.
    """
    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_tenant_created", "tenant_id", "created_at"),
        Index("ix_analytics_tenant_provider_model_created", "tenant_id", "provider", "model", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    metadata_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="analytics_events")


class RequestLog(Base):
    """
    Immutable request lifecycle record for dashboard views and troubleshooting.

    This stores the per-request metadata that the dashboard and audit screens
    need without mixing it into the analytics aggregate.
    """
    __tablename__ = "request_logs"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_request_logs_request_id"),
        Index("ix_request_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_request_logs_tenant_status_created", "tenant_id", "status_code", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    request_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True, default=dict)
    response_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON_TYPE, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant: Mapped["Tenant"] = relationship("Tenant")


class AnalyticsOutbox(Base):
    """
    Durable delivery queue for analytics events.

    Keeps the request path decoupled from persistence while preserving
    at-least-once delivery semantics for background workers.
    """
    __tablename__ = "analytics_outbox"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_analytics_outbox_request_id"),
        Index("ix_analytics_outbox_status_created", "delivery_status", "created_at"),
        Index("ix_analytics_outbox_tenant_status", "tenant_id", "delivery_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    delivery_status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant: Mapped["Tenant"] = relationship("Tenant")


class DeadLetterEvent(Base):
    """
    Archive for events that exhausted retries or failed irrecoverably.

    Enables safe manual replay and operational inspection.
    """
    __tablename__ = "dead_letter_events"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_dead_letter_request_id"),
        Index("ix_dead_letter_created", "created_at"),
        Index("ix_dead_letter_tenant", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID_TYPE, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    failure_reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    tenant: Mapped["Tenant"] = relationship("Tenant")
