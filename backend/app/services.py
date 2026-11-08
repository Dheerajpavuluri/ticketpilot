from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from statistics import mean

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .agent import run_agent
from .config import Settings
from .config import settings as default_settings
from .db import RefundRequest, ReviewEvent, Ticket, Triage
from .llm import Provider, get_provider

log = logging.getLogger("ticketpilot")

DATASET = Path(__file__).resolve().parent.parent / "evals" / "dataset.jsonl"


class NotFound(Exception):
    pass


class InvalidState(Exception):
    pass


def create_ticket(session: Session, customer_email: str, subject: str, body: str) -> Ticket:
    ticket = Ticket(
        id=uuid.uuid4().hex[:12],
        customer_email=customer_email.strip().lower(),
        subject=subject.strip(),
        body=body.strip(),
    )
    session.add(ticket)
    session.commit()
    return ticket


def get_ticket(session: Session, ticket_id: str) -> Ticket:
    ticket = session.scalar(
        select(Ticket)
        .where(Ticket.id == ticket_id)
        .options(selectinload(Ticket.triage), selectinload(Ticket.events), selectinload(Ticket.refunds))
    )
    if ticket is None:
        raise NotFound(ticket_id)
    return ticket


def list_tickets(session: Session, status: str | None = None, limit: int = 200) -> list[Ticket]:
    q = select(Ticket).options(selectinload(Ticket.triage)).order_by(Ticket.created_at.desc())
    if status:
        q = q.where(Ticket.status == status)
    return list(session.scalars(q.limit(limit)))


def triage_ticket(
    session: Session,
    ticket_id: str,
    provider: Provider | None = None,
    cfg: Settings = default_settings,
    raise_errors: bool = False,
) -> Ticket:
    """Run the agent on a ticket and store the result.

    With raise_errors=True a failure is re-raised after the ticket is marked
    failed, so a queue worker can retry it.
    """
    ticket = get_ticket(session, ticket_id)
    provider = provider or get_provider(cfg)
    ticket.status = "triaging"
    ticket.error = None
    session.commit()

    try:
        # retriage starts clean: drop the previous result and any refund it opened
        if ticket.triage is not None:
            session.delete(ticket.triage)
        for r in list(ticket.refunds):
            if r.status == "pending":
                session.delete(r)
        session.flush()

        result = run_agent(session, ticket, provider, cfg)
        out = result.output
        session.add(
            Triage(
                ticket_id=ticket.id,
                category=out.category,
                priority=result.priority,
                sentiment=out.sentiment,
                summary=out.summary,
                order_id=out.order_id,
                draft_reply=out.draft_reply,
                citations=out.citations,
                confidence=out.confidence,
                needs_human=result.needs_human,
                escalation_reasons=result.escalation_reasons,
                trace=result.trace,
                provider=provider.name,
                model=provider.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
            )
        )
        if result.needs_human:
            ticket.status = "needs_review"
        else:
            ticket.status = "auto_resolved"
            session.add(ReviewEvent(ticket_id=ticket.id, action="auto_sent", final_reply=out.draft_reply))
        session.commit()
    except Exception as exc:
        session.rollback()
        ticket = session.get(Ticket, ticket_id)
        ticket.status = "failed"
        ticket.error = f"{type(exc).__name__}: {exc}"[:2000]
        session.commit()
        log.exception("triage failed for %s", ticket_id)
        if raise_errors:
            raise
    session.expire_all()
    return get_ticket(session, ticket_id)


def approve(session: Session, ticket_id: str, reply: str | None, actor: str) -> Ticket:
    ticket = get_ticket(session, ticket_id)
    if ticket.status != "needs_review" or ticket.triage is None:
        raise InvalidState(f"ticket is {ticket.status}, only tickets in review can be approved")
    final = (reply or ticket.triage.draft_reply).strip()
    edited = final != ticket.triage.draft_reply.strip()
    for r in ticket.refunds:
        if r.status == "pending":
            r.status = "approved"
    session.add(
        ReviewEvent(ticket_id=ticket.id, action="edited" if edited else "approved", actor=actor, final_reply=final)
    )
    ticket.status = "sent"
    session.commit()
    session.expire_all()
    return get_ticket(session, ticket_id)


def reject(session: Session, ticket_id: str, note: str, actor: str) -> Ticket:
    ticket = get_ticket(session, ticket_id)
    if ticket.status not in ("needs_review", "failed"):
        raise InvalidState(f"ticket is {ticket.status}")
    session.add(ReviewEvent(ticket_id=ticket.id, action="rejected", actor=actor, note=note))
    ticket.status = "rejected"
    session.commit()
    session.expire_all()
    return get_ticket(session, ticket_id)


def stats(session: Session, cfg: Settings = default_settings) -> dict:
    by_status = dict(session.execute(select(Ticket.status, func.count()).group_by(Ticket.status)).all())
    by_category = dict(session.execute(select(Triage.category, func.count()).group_by(Triage.category)).all())
    triages = list(session.scalars(select(Triage)))
    edited = session.scalar(select(func.count()).where(ReviewEvent.action == "edited")) or 0
    reviewed = session.scalar(select(func.count()).where(ReviewEvent.action.in_(["approved", "edited"]))) or 0
    pending_refunds = session.scalar(
        select(func.coalesce(func.sum(RefundRequest.amount), 0)).where(RefundRequest.status == "pending")
    )
    done = len(triages)
    auto = sum(1 for t in triages if not t.needs_human)
    tin = sum(t.input_tokens for t in triages)
    tout = sum(t.output_tokens for t in triages)
    cost = None
    if cfg.price_input_per_mtok or cfg.price_output_per_mtok:
        cost = round(tin / 1e6 * cfg.price_input_per_mtok + tout / 1e6 * cfg.price_output_per_mtok, 4)
    return {
        "total_tickets": sum(by_status.values()),
        "by_status": by_status,
        "by_category": by_category,
        "triaged": done,
        "auto_resolve_rate": round(auto / done, 3) if done else None,
        "avg_confidence": round(mean(t.confidence for t in triages), 3) if done else None,
        "avg_latency_ms": round(mean(t.latency_ms for t in triages)) if done else None,
        "human_edit_rate": round(edited / reviewed, 3) if reviewed else None,
        "pending_refund_total": round(float(pending_refunds or 0), 2),
        "tokens": {"input": tin, "output": tout},
        "estimated_cost_usd": cost,
    }


def load_demo_tickets(session: Session, limit: int | None = None) -> list[Ticket]:
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    tickets = [create_ticket(session, r["customer_email"], r["subject"], r["body"]) for r in rows[:limit]]
    return tickets
