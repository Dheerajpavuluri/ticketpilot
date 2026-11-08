"""Deterministic guardrails applied after the model decides.

The model's own `needs_human` is a suggestion. These rules can only make the
outcome *more* cautious: they add escalation reasons or raise priority, never
remove them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import Settings

PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2, "urgent": 3}

SAFETY_RE = re.compile(r"\b(spark\w*|smok\w*|fire|burn\w*|shock\w*|electrocut\w*|melt\w*)\b", re.I)
LEGAL_RE = re.compile(r"\b(lawyer|attorney|sue|lawsuit|legal action|chargeback|dispute)\b", re.I)
DUPLICATE_CHARGE_RE = re.compile(r"\b(double[- ]?charged?|charged twice|duplicate charge|two charges)\b", re.I)
DELETION_RE = re.compile(r"\b(delete|erase|remove)\b.{0,30}\b(account|data)\b", re.I)


@dataclass
class PolicyResult:
    needs_human: bool
    priority: str
    reasons: list[str] = field(default_factory=list)


def _raise(priority: str, floor: str) -> str:
    return floor if PRIORITY_RANK[floor] > PRIORITY_RANK[priority] else priority


def apply_policy(
    text: str,
    priority: str,
    model_needs_human: bool,
    model_reason: str | None,
    confidence: float,
    refund_amounts: list[float],
    grounding_issues: list[str],
    cfg: Settings,
) -> PolicyResult:
    reasons: list[str] = []
    if model_needs_human:
        reasons.append(f"model: {model_reason or 'requested human review'}")

    if SAFETY_RE.search(text):
        reasons.append("possible safety hazard reported")
        priority = _raise(priority, "urgent")
    if LEGAL_RE.search(text):
        reasons.append("legal threat or payment dispute")
        priority = _raise(priority, "high")
    if DELETION_RE.search(text):
        reasons.append("account/data deletion needs identity verification")
    big = [a for a in refund_amounts if a > cfg.refund_review_limit]
    if big:
        reasons.append(f"refund of ${max(big):.2f} exceeds ${cfg.refund_review_limit:.0f} auto-approve limit")
    if confidence < cfg.auto_send_confidence:
        reasons.append(f"low confidence ({confidence:.2f})")
    reasons.extend(grounding_issues)

    return PolicyResult(needs_human=bool(reasons), priority=priority, reasons=reasons)
