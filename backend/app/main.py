from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import services
from .config import settings
from .db import SessionLocal, Ticket, init_db
from .dispatch import Dispatcher
from .retrieval import help_center

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.dispatcher = Dispatcher()
    yield
    await app.state.dispatcher.close()


app = FastAPI(title="TicketPilot", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


# ---- schemas ---------------------------------------------------------------


class TicketIn(BaseModel):
    customer_email: EmailStr
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10_000)


class ApproveIn(BaseModel):
    reply: str | None = Field(default=None, max_length=10_000)
    actor: str = Field(default="agent", max_length=80)


class RejectIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
    actor: str = Field(default="agent", max_length=80)


def triage_dict(t) -> dict[str, Any] | None:
    if t is None:
        return None
    return {
        "category": t.category,
        "priority": t.priority,
        "sentiment": t.sentiment,
        "summary": t.summary,
        "order_id": t.order_id,
        "draft_reply": t.draft_reply,
        "citations": t.citations,
        "confidence": t.confidence,
        "needs_human": t.needs_human,
        "escalation_reasons": t.escalation_reasons,
        "provider": t.provider,
        "model": t.model,
        "input_tokens": t.input_tokens,
        "output_tokens": t.output_tokens,
        "latency_ms": t.latency_ms,
    }


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def ticket_summary(t: Ticket) -> dict[str, Any]:
    tr = t.triage
    return {
        "id": t.id,
        "customer_email": t.customer_email,
        "subject": t.subject,
        "status": t.status,
        "created_at": _iso(t.created_at),
        "category": tr.category if tr else None,
        "priority": tr.priority if tr else None,
        "sentiment": tr.sentiment if tr else None,
        "confidence": tr.confidence if tr else None,
        "needs_human": tr.needs_human if tr else None,
    }


def ticket_detail(t: Ticket) -> dict[str, Any]:
    return {
        **ticket_summary(t),
        "body": t.body,
        "error": t.error,
        "triage": triage_dict(t.triage),
        "trace": t.triage.trace if t.triage else [],
        "events": [
            {
                "action": e.action,
                "actor": e.actor,
                "note": e.note,
                "final_reply": e.final_reply,
                "created_at": _iso(e.created_at),
            }
            for e in t.events
        ],
        "refunds": [
            {"order_id": r.order_id, "amount": r.amount, "reason": r.reason, "status": r.status} for r in t.refunds
        ],
    }


def _get(session: Session, ticket_id: str) -> Ticket:
    try:
        return services.get_ticket(session, ticket_id)
    except services.NotFound:
        raise HTTPException(404, "ticket not found") from None


# ---- routes ----------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "provider": settings.llm_provider, "mode": settings.processing_mode}


@app.get("/api/tickets")
def list_tickets(status: str | None = Query(None), session: Session = Depends(get_session)) -> list[dict]:
    return [ticket_summary(t) for t in services.list_tickets(session, status)]


@app.post("/api/tickets", status_code=202)
async def create_ticket(body: TicketIn, background: BackgroundTasks, session: Session = Depends(get_session)) -> dict:
    ticket = await run_in_threadpool(services.create_ticket, session, body.customer_email, body.subject, body.body)
    await app.state.dispatcher.dispatch(ticket.id, background, idempotency_key=f"triage:{ticket.id}")
    return ticket_summary(ticket)


@app.get("/api/tickets/{ticket_id}")
def get_ticket(ticket_id: str, session: Session = Depends(get_session)) -> dict:
    return ticket_detail(_get(session, ticket_id))


@app.post("/api/tickets/{ticket_id}/retriage", status_code=202)
async def retriage(ticket_id: str, background: BackgroundTasks, session: Session = Depends(get_session)) -> dict:
    ticket = await run_in_threadpool(_get, session, ticket_id)
    if ticket.status in ("sent", "triaging"):
        raise HTTPException(409, f"ticket is {ticket.status}")
    await app.state.dispatcher.dispatch(
        ticket.id, background, idempotency_key=f"retriage:{ticket.id}:{uuid.uuid4().hex}"
    )
    return {"id": ticket.id, "status": "queued"}


@app.post("/api/tickets/{ticket_id}/approve")
def approve(ticket_id: str, body: ApproveIn, session: Session = Depends(get_session)) -> dict:
    _get(session, ticket_id)
    try:
        return ticket_detail(services.approve(session, ticket_id, body.reply, body.actor))
    except services.InvalidState as exc:
        raise HTTPException(409, str(exc)) from None


@app.post("/api/tickets/{ticket_id}/reject")
def reject(ticket_id: str, body: RejectIn, session: Session = Depends(get_session)) -> dict:
    _get(session, ticket_id)
    try:
        return ticket_detail(services.reject(session, ticket_id, body.note, body.actor))
    except services.InvalidState as exc:
        raise HTTPException(409, str(exc)) from None


@app.get("/api/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    return services.stats(session)


@app.get("/api/articles/{slug}")
def article(slug: str) -> dict:
    a = help_center().get(slug)
    if a is None:
        raise HTTPException(404, "article not found")
    return {"slug": a.slug, "title": a.title, "category": a.category, "body": a.body}


@app.post("/api/demo/load", status_code=202)
async def load_demo(
    background: BackgroundTasks,
    limit: int = Query(12, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict:
    tickets = await run_in_threadpool(services.load_demo_tickets, session, limit)
    for t in tickets:
        await app.state.dispatcher.dispatch(t.id, background, idempotency_key=f"triage:{t.id}")
    return {"loaded": len(tickets)}


# ---- frontend (single-container deploys serve the built React app) ---------

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")
