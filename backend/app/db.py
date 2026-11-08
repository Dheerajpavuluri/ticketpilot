from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings

SEED_DIR = Path(__file__).parent / "seed"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    customer_since: Mapped[str] = mapped_column(String(10))
    vip: Mapped[bool] = mapped_column(Boolean, default=False)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    placed_at: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))
    delivered_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    items: Mapped[list] = mapped_column(JSON)
    total: Mapped[float] = mapped_column(Float)
    tracking_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(10), nullable=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    plan: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    next_ship_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    canceled_at: Mapped[str | None] = mapped_column(String(10), nullable=True)
    price: Mapped[float] = mapped_column(Float)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_email: Mapped[str] = mapped_column(String(200), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    # new -> triaging -> needs_review | auto_resolved -> sent ; failed / rejected
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    triage: Mapped[Triage | None] = relationship(back_populates="ticket", uselist=False, cascade="all, delete-orphan")
    events: Mapped[list[ReviewEvent]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="ReviewEvent.id"
    )
    refunds: Mapped[list[RefundRequest]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class Triage(Base):
    __tablename__ = "triages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), unique=True)
    category: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(10))
    sentiment: Mapped[str] = mapped_column(String(15))
    summary: Mapped[str] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    draft_reply: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    needs_human: Mapped[bool] = mapped_column(Boolean)
    escalation_reasons: Mapped[list] = mapped_column(JSON, default=list)
    trace: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="triage")


class ReviewEvent(Base):
    __tablename__ = "review_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    # auto_sent | approved | edited | rejected | retriaged
    action: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(80), default="system")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="events")


class RefundRequest(Base):
    __tablename__ = "refund_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.id"), index=True)
    order_id: Mapped[str] = mapped_column(String(20))
    amount: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | approved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="refunds")


def make_engine(url: str | None = None):
    url = url or settings.database_url
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(eng=None, session_factory=None) -> None:
    eng = eng or engine
    Base.metadata.create_all(eng)
    factory = session_factory or sessionmaker(bind=eng, expire_on_commit=False)
    with factory() as session:
        seed_store(session)


def seed_store(session) -> None:
    """Load the sample store (customers, orders, subscriptions) once."""
    if session.scalar(select(Customer.id).limit(1)):
        return
    data = json.loads((SEED_DIR / "store.json").read_text())
    session.add_all(Customer(**c) for c in data["customers"])
    session.add_all(Order(**o) for o in data["orders"])
    session.add_all(Subscription(**s) for s in data["subscriptions"])
    session.commit()
