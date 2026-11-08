import os
import tempfile

# must be set before app modules are imported (engine + settings read env at import)
_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite:///{_db.name}"
os.environ["LLM_PROVIDER"] = "offline"
os.environ["TODAY"] = "2026-11-06"
os.environ["PROCESSING_MODE"] = "inline"

import pytest  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import init_db, make_engine  # noqa: E402
from app.llm.base import LLMResponse, ToolCall  # noqa: E402


@pytest.fixture
def cfg():
    return Settings()


@pytest.fixture
def session():
    engine = make_engine("sqlite://")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    init_db(engine, factory)
    with factory() as s:
        yield s
    engine.dispose()


class ScriptedProvider:
    """Plays back a fixed list of model turns."""

    name = "scripted"
    model = "scripted-1"

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen = []

    def chat(self, system, messages, tools):
        self.seen.append([dict(m) for m in messages])
        if not self.turns:
            return LLMResponse(text="I'm done.")
        calls = self.turns.pop(0)
        return LLMResponse(
            text=None,
            tool_calls=[ToolCall(f"c{i}-{len(self.seen)}", name, args) for i, (name, args) in enumerate(calls)],
            input_tokens=100,
            output_tokens=20,
        )


def submit(**overrides):
    args = {
        "category": "shipping",
        "priority": "medium",
        "sentiment": "neutral",
        "summary": "Customer asks where their order is",
        "order_id": None,
        "draft_reply": "Hi! Your order is on the way.\n\nBrewline Support",
        "citations": [],
        "confidence": 0.9,
        "needs_human": False,
        "escalation_reason": None,
    }
    args.update(overrides)
    return ("submit_triage", args)
