from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from .config import Settings
from .config import settings as default_settings
from .db import Order, Ticket
from .llm import Message, Provider
from .policy import DUPLICATE_CHARGE_RE, apply_policy
from .tools import (
    CATEGORIES,
    HANDLERS,
    PRIORITIES,
    SENTIMENTS,
    TOOL_SPECS,
    ToolContext,
    ToolError,
)

SYSTEM_PROMPT = """You are a support agent for Brewline, an online store that sells espresso \
machines, grinders, kettles and coffee subscriptions.

For each ticket:
1. Look up the customer by email. If the ticket mentions an order, fetch it with get_order. If it \
doesn't, check the customer's recent orders and fetch the one the ticket is about.
2. Search the help center before stating any policy, timeline or fee. Only promise what the \
articles say. Never invent order details, tracking numbers or dates.
3. If the customer asks for their money back and policy allows it, open a refund request.
4. Call submit_triage once with your classification and a reply draft.

Reply style: warm, specific, short (under 150 words). Use the customer's first name, reference \
their order details, give the concrete next step. Sign off as "Brewline Support".

Set needs_human=true when: there is any safety risk, legal threat or payment dispute; the \
customer wants account deletion; a refund needs approval; you are unsure what they want; or the \
right answer isn't in the help center.

Priority guide: urgent = safety risk; high = money at stake (double charge, dispute, lost or \
damaged item, defective product); medium = an order needs action; low = general questions.
Confidence: how sure you are that the reply is correct and complete, from 0 to 1."""

ORDER_RE = re.compile(r"\bBL-\d{5}\b", re.I)
MAX_RESULT_CHARS = 4000


class TriageOutput(BaseModel):
    category: str
    priority: str
    sentiment: str
    summary: str = Field(min_length=1, max_length=500)
    order_id: str | None = None
    draft_reply: str = Field(min_length=1)
    citations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    needs_human: bool
    escalation_reason: str | None = None

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        return v

    @field_validator("priority")
    @classmethod
    def _prio(cls, v: str) -> str:
        if v not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}")
        return v

    @field_validator("sentiment")
    @classmethod
    def _sent(cls, v: str) -> str:
        if v not in SENTIMENTS:
            raise ValueError(f"sentiment must be one of {SENTIMENTS}")
        return v


@dataclass
class AgentResult:
    output: TriageOutput
    needs_human: bool
    priority: str
    escalation_reasons: list[str]
    trace: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    finished: bool = True


def ticket_prompt(ticket: Ticket) -> str:
    payload = {
        "ticket_id": ticket.id,
        "customer_email": ticket.customer_email,
        "subject": ticket.subject,
        "body": ticket.body,
    }
    return "New support ticket:\n```json\n" + json.dumps(payload, indent=2) + "\n```"


def _truncate(obj: Any) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= MAX_RESULT_CHARS else s[:MAX_RESULT_CHARS] + "...(truncated)"


def run_agent(session, ticket: Ticket, provider: Provider, cfg: Settings = default_settings) -> AgentResult:
    ctx = ToolContext(session=session, ticket=ticket, settings=cfg)
    messages: list[Message] = [{"role": "user", "content": ticket_prompt(ticket)}]
    trace: list[dict[str, Any]] = []
    tokens_in = tokens_out = 0
    started = time.perf_counter()
    nudged = False
    final: TriageOutput | None = None

    for step in range(1, cfg.max_agent_steps + 1):
        t0 = time.perf_counter()
        resp = provider.chat(SYSTEM_PROMPT, messages, TOOL_SPECS)
        tokens_in += resp.input_tokens
        tokens_out += resp.output_tokens
        trace.append(
            {
                "step": step,
                "type": "model",
                "text": resp.text,
                "tool_calls": [tc.name for tc in resp.tool_calls],
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "ms": round((time.perf_counter() - t0) * 1000),
            }
        )
        messages.append({"role": "assistant", "content": resp.text, "tool_calls": resp.tool_calls})

        if not resp.tool_calls:
            if nudged:
                break
            nudged = True
            messages.append({"role": "user", "content": "Use the tools, then call submit_triage to finish."})
            continue

        for tc in resp.tool_calls:
            t1 = time.perf_counter()
            if tc.name == "submit_triage":
                try:
                    final = TriageOutput.model_validate(tc.arguments)
                    result: Any = {"ok": True}
                except ValidationError as exc:
                    result = {"error": f"invalid submission: {exc.errors(include_url=False)}"}
            elif tc.name in HANDLERS:
                try:
                    result = HANDLERS[tc.name](ctx, **tc.arguments)
                except ToolError as exc:
                    result = {"error": str(exc)}
                except TypeError as exc:
                    result = {"error": f"bad arguments: {exc}"}
            else:
                result = {"error": f"unknown tool {tc.name}"}

            trace.append(
                {
                    "step": step,
                    "type": "tool",
                    "tool": tc.name,
                    "args": tc.arguments,
                    "result": result,
                    "ms": round((time.perf_counter() - t1) * 1000),
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": _truncate(result),
                }
            )
        if final is not None:
            break

    finished = final is not None
    if final is None:
        final = TriageOutput(
            category="general",
            priority="medium",
            sentiment="neutral",
            summary=ticket.subject[:500] or "(no subject)",
            draft_reply="(the agent did not produce a reply)",
            confidence=0.0,
            needs_human=True,
            escalation_reason="agent did not finish within the step limit",
        )

    # grounding: a reply may only cite articles the agent actually retrieved
    grounding: list[str] = []
    cited = [c for c in final.citations if c in ctx.retrieved]
    if len(cited) != len(final.citations):
        bogus = sorted(set(final.citations) - ctx.retrieved)
        grounding.append(f"cited articles it never retrieved: {', '.join(bogus)}")
        final.citations = cited
    if final.order_id:
        oid = final.order_id.upper()
        if oid not in ctx.looked_up_orders and oid not in ticket.body.upper():
            grounding.append(f"referenced order {oid} without looking it up")
            final.order_id = None
        else:
            final.order_id = oid

    # a duplicate-charge claim is a refund in disguise, even if the model didn't open one
    money_at_stake = [r.amount for r in ctx.refund_requests]
    if DUPLICATE_CHARGE_RE.search(f"{ticket.subject} {ticket.body}"):
        for oid in ctx.looked_up_orders:
            order = session.get(Order, oid)
            if order:
                money_at_stake.append(order.total)

    policy = apply_policy(
        text=f"{ticket.subject}\n{ticket.body}",
        priority=final.priority,
        model_needs_human=final.needs_human,
        model_reason=final.escalation_reason,
        confidence=final.confidence,
        refund_amounts=money_at_stake,
        grounding_issues=grounding,
        cfg=cfg,
    )
    return AgentResult(
        output=final,
        needs_human=policy.needs_human,
        priority=policy.priority,
        escalation_reasons=policy.reasons,
        trace=trace,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        latency_ms=round((time.perf_counter() - started) * 1000),
        finished=finished,
    )
