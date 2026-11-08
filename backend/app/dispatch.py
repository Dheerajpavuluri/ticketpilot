"""How a new ticket gets triaged.

inline: FastAPI background task in the API process. Zero infrastructure, good
        for local dev and the demo.
queue:  enqueue a job on taskforge (Redis). Separate worker processes run the
        agent, so slow LLM calls never tie up the API and crashed runs retry.
"""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks

from .config import settings
from .db import SessionLocal

log = logging.getLogger("ticketpilot.dispatch")

TRIAGE_TASK = "triage_ticket"


def run_triage_job(ticket_id: str, raise_errors: bool = False) -> None:
    from .services import triage_ticket

    with SessionLocal() as session:
        triage_ticket(session, ticket_id, raise_errors=raise_errors)


class Dispatcher:
    def __init__(self) -> None:
        self.mode = settings.processing_mode
        self._broker = None
        if self.mode == "queue":
            from taskforge import Broker

            self._broker = Broker.from_url(settings.redis_url)

    async def dispatch(self, ticket_id: str, background: BackgroundTasks, idempotency_key: str | None = None) -> None:
        if self._broker is None:
            background.add_task(run_triage_job, ticket_id)
            return
        from taskforge import Priority, TaskIn

        await self._broker.enqueue(
            TaskIn(
                name=TRIAGE_TASK,
                payload={"ticket_id": ticket_id},
                priority=Priority.default,
                max_retries=2,
                timeout=180,
                # e.g. "triage:<id>" so a retried HTTP request doesn't triage twice
                idempotency_key=idempotency_key,
            )
        )

    async def close(self) -> None:
        if self._broker is not None:
            await self._broker.close()
