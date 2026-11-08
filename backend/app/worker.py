"""taskforge worker for PROCESSING_MODE=queue.

python -m app.worker --concurrency 4
"""

import asyncio

from taskforge import task

from .db import init_db
from .dispatch import TRIAGE_TASK, run_triage_job


@task(TRIAGE_TASK)
async def triage(payload: dict) -> dict:
    # the agent and DB layer are synchronous; keep them off the event loop
    # raise_errors so taskforge retries transient LLM/API failures with backoff
    await asyncio.to_thread(run_triage_job, payload["ticket_id"], True)
    return {"ticket_id": payload["ticket_id"]}


def main() -> None:
    init_db()
    from taskforge.worker import main as taskforge_main

    taskforge_main()


if __name__ == "__main__":
    main()
