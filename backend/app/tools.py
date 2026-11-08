"""Tools the agent can call. Each one reads or writes the store through the
session in ToolContext and returns plain JSON-serializable data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .db import Customer, Order, RefundRequest, Subscription, Ticket
from .llm.base import ToolSpec
from .retrieval import help_center

CATEGORIES = [
    "shipping",
    "returns_refunds",
    "product_issue",
    "billing",
    "subscription",
    "account",
    "general",
]
PRIORITIES = ["low", "medium", "high", "urgent"]
SENTIMENTS = ["positive", "neutral", "frustrated", "angry"]


@dataclass
class ToolContext:
    session: Session
    ticket: Ticket
    settings: Settings
    retrieved: set[str] = field(default_factory=set)  # article slugs the agent actually saw
    looked_up_orders: set[str] = field(default_factory=set)
    refund_requests: list[RefundRequest] = field(default_factory=list)


class ToolError(Exception):
    """Returned to the model as an error result instead of crashing the run."""


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="lookup_customer",
        description=("Look up a customer by email. Returns profile, VIP flag, recent orders and subscription status."),
        parameters={
            "type": "object",
            "properties": {"email": {"type": "string"}},
            "required": ["email"],
        },
    ),
    ToolSpec(
        name="get_order",
        description=(
            "Get full details for one order: items, total, status, carrier, tracking "
            "number, delivery date and days since delivery."
        ),
        parameters={
            "type": "object",
            "properties": {"order_id": {"type": "string", "description": "e.g. BL-48213"}},
            "required": ["order_id"],
        },
    ),
    ToolSpec(
        name="search_help_center",
        description=(
            "Search Brewline help-center articles (policies, shipping, warranty, how-to). "
            "Use it before stating any policy. Returns article slugs, titles and the best "
            "matching passage."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="create_refund_request",
        description=(
            "Open a refund request for an order. Refunds above the review limit are held "
            "for a human to approve. Only use when the customer asks for money back and "
            "policy allows it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "amount": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["order_id", "amount", "reason"],
        },
    ),
    ToolSpec(
        name="submit_triage",
        description="Finish the ticket. Call exactly once, after gathering what you need.",
        parameters={
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "priority": {"type": "string", "enum": PRIORITIES},
                "sentiment": {"type": "string", "enum": SENTIMENTS},
                "summary": {"type": "string", "description": "One sentence for the agent queue"},
                "order_id": {"type": ["string", "null"]},
                "draft_reply": {"type": "string", "description": "Reply to send the customer"},
                "citations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Slugs of help-center articles the reply relies on",
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "needs_human": {"type": "boolean"},
                "escalation_reason": {"type": ["string", "null"]},
            },
            "required": [
                "category",
                "priority",
                "sentiment",
                "summary",
                "draft_reply",
                "citations",
                "confidence",
                "needs_human",
            ],
        },
    ),
]


def _order_dict(order: Order, today: date) -> dict[str, Any]:
    days = None
    if order.delivered_at:
        days = (today - date.fromisoformat(order.delivered_at)).days
    return {
        "order_id": order.id,
        "placed_at": order.placed_at,
        "status": order.status,
        "items": [i["name"] for i in order.items],
        "item_prices": {i["name"]: i["price"] for i in order.items},
        "total": order.total,
        "carrier": order.carrier,
        "tracking_number": order.tracking_number,
        "delivered_at": order.delivered_at,
        "days_since_delivery": days,
    }


def lookup_customer(ctx: ToolContext, email: str) -> dict[str, Any]:
    email = email.strip().lower()
    cust = ctx.session.scalar(select(Customer).where(Customer.email == email))
    if cust is None:
        return {"found": False, "email": email}
    orders = ctx.session.scalars(
        select(Order).where(Order.customer_id == cust.id).order_by(Order.placed_at.desc())
    ).all()
    sub = ctx.session.scalar(select(Subscription).where(Subscription.customer_id == cust.id))
    return {
        "found": True,
        "customer_id": cust.id,
        "name": cust.name,
        "vip": cust.vip,
        "customer_since": cust.customer_since,
        "recent_orders": [
            {
                "order_id": o.id,
                "placed_at": o.placed_at,
                "status": o.status,
                "total": o.total,
                "items": [i["name"] for i in o.items],
            }
            for o in orders[:5]
        ],
        "subscription": (
            {
                "plan": sub.plan,
                "status": sub.status,
                "next_ship_date": sub.next_ship_date,
                "canceled_at": sub.canceled_at,
                "price": sub.price,
            }
            if sub
            else None
        ),
    }


def get_order(ctx: ToolContext, order_id: str) -> dict[str, Any]:
    order_id = order_id.strip().upper()
    order = ctx.session.get(Order, order_id)
    if order is None:
        raise ToolError(f"order {order_id} not found")
    # don't leak other customers' orders to whoever wrote the ticket
    owner = ctx.session.get(Customer, order.customer_id)
    if owner and owner.email != ctx.ticket.customer_email.lower():
        raise ToolError(f"order {order_id} does not belong to the ticket's customer")
    ctx.looked_up_orders.add(order.id)
    return _order_dict(order, ctx.settings.today())


def search_help_center(ctx: ToolContext, query: str) -> dict[str, Any]:
    hits = help_center().search(query, k=3)
    ctx.retrieved.update(h.slug for h in hits)
    return {"results": [{"slug": h.slug, "title": h.title, "passage": h.snippet, "score": h.score} for h in hits]}


def create_refund_request(ctx: ToolContext, order_id: str, amount: float, reason: str) -> dict[str, Any]:
    order_id = order_id.strip().upper()
    order = ctx.session.get(Order, order_id)
    if order is None or order_id not in ctx.looked_up_orders:
        raise ToolError("look the order up with get_order before requesting a refund")
    amount = round(float(amount), 2)
    if amount <= 0 or amount > order.total:
        raise ToolError(f"amount must be between 0 and the order total ({order.total})")
    req = RefundRequest(ticket_id=ctx.ticket.id, order_id=order_id, amount=amount, reason=reason)
    ctx.session.add(req)
    ctx.refund_requests.append(req)
    needs_review = amount > ctx.settings.refund_review_limit
    return {
        "status": "pending_review" if needs_review else "approved_pending_return",
        "amount": amount,
        "requires_human_approval": needs_review,
    }


HANDLERS = {
    "lookup_customer": lookup_customer,
    "get_order": get_order,
    "search_help_center": search_help_center,
    "create_refund_request": create_refund_request,
}
