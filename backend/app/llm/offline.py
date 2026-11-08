"""Rule-based stand-in for an LLM.

It speaks the same tool-calling protocol as the real providers, so the whole
pipeline (tools, trace, policy, UI) runs without an API key. It is also the
baseline the eval harness compares real models against.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import LLMResponse, Message, ToolCall, ToolSpec

ORDER_RE = re.compile(r"\bBL-\d{5}\b", re.I)

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "billing": ["charge", "charged", "double", "dispute", "chargeback", "card", "payment", "pending"],
    "subscription": ["subscription", "skip", "pause"],
    "account": ["password", "log in", "login", "delete my account", "my data", "account"],
    "returns_refunds": ["return", "refund", "exchange", "money back", "send it back"],
    "shipping": [
        "tracking",
        "ship",
        "shipped",
        "delivered",
        "where is",
        "address",
        "cancel order",
        "cancel my order",
        "expedited",
        "canada",
        "arrive",
        "get here",
    ],
    "product_issue": [
        "leak",
        "spark",
        "noise",
        "heating",
        "pressure",
        "broken",
        "damaged",
        "dent",
        "crushed",
        "sour",
        "descale",
        "wrong",
        "defective",
        "burned",
        "overheat",
        "hums",
        "not working",
    ],
}
# when scores tie, earlier wins
CATEGORY_PRECEDENCE = ["billing", "subscription", "account", "returns_refunds", "product_issue", "shipping"]
SAFETY = ["spark", "smoke", "fire", "burn", "shock", "electrocut"]
LEGAL = ["lawyer", "attorney", "sue ", "chargeback", "dispute"]
HIGH = [
    "double",
    "damaged",
    "dent",
    "crushed",
    "delivered yesterday",
    "says delivered",
    "leak",
    "not heating",
    "stopped heating",
    "defective",
    "asap",
]
ITEM_HINTS = {
    "aurora": "Aurora Espresso Machine",
    "espresso machine": "Aurora Espresso Machine",
    "machine": "Aurora Espresso Machine",
    "grinder": "Cascade Burr Grinder",
    "kettle": "Pour-Over Kettle",
    "descaler": "Descaler 3-Pack",
    "pitcher": "Milk Pitcher",
    "tamper": "Tamper Set",
    "subscription box": "Monthly Subscription Box",
    "house blend": "House Blend 2lb",
}


def _has(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def classify(text: str) -> str:
    scores = {c: sum(text.count(w) for w in ws) for c, ws in CATEGORY_KEYWORDS.items()}
    best = max(scores.values())
    if best == 0:
        return "general"
    for cat in CATEGORY_PRECEDENCE:
        if scores[cat] == best:
            return cat
    return "general"


def prioritize(text: str, category: str) -> str:
    if _has(text, SAFETY):
        return "urgent"
    if _has(text, LEGAL) or _has(text, HIGH):
        return "high"
    question = text.strip().endswith("?") or text.startswith(("how", "can i", "should", "do you"))
    if category in ("general", "account") or (question and not ORDER_RE.search(text)):
        return "low"
    return "medium"


def sentiment(raw: str) -> str:
    t = raw.lower()
    if "!!" in raw or _has(t, ["lawyer", "unacceptable", "ridiculous"]):
        return "angry"
    if _has(t, ["asap", "scary", "frustrat", "nothing at my door", "still haven", "still not"]):
        return "frustrated"
    if _has(t, ["great", "excited", "love", "thanks!"]):
        return "positive"
    return "neutral"


class OfflineProvider:
    name = "offline"
    model = "rules-v1"

    def __init__(self) -> None:
        self._n = 0

    def _id(self) -> str:
        self._n += 1
        return f"call_{self._n}"

    def chat(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> LLMResponse:
        ticket = json.loads(messages[0]["content"].split("```json", 1)[1].split("```", 1)[0])
        raw = f"{ticket['subject']}\n{ticket['body']}"
        text = raw.lower()
        results = {m["name"]: json.loads(m["content"]) for m in messages if m["role"] == "tool"}
        turns = sum(1 for m in messages if m["role"] == "assistant")

        if turns == 0:
            calls = [
                ToolCall(self._id(), "lookup_customer", {"email": ticket["customer_email"]}),
                ToolCall(self._id(), "search_help_center", {"query": raw}),
            ]
            for oid in dict.fromkeys(m.upper() for m in ORDER_RE.findall(raw)):
                calls.append(ToolCall(self._id(), "get_order", {"order_id": oid}))
            return LLMResponse(text=None, tool_calls=calls)

        category = classify(text)
        order = results.get("get_order") if "error" not in results.get("get_order", {}) else None

        if turns == 1:
            follow: list[ToolCall] = []
            # no order number in the ticket: guess it from the products mentioned
            if order is None and category not in ("general", "account", "subscription"):
                cust = results.get("lookup_customer", {})
                wanted = {name for hint, name in ITEM_HINTS.items() if hint in text}
                for o in cust.get("recent_orders", []):
                    if wanted & set(o["items"]):
                        follow.append(ToolCall(self._id(), "get_order", {"order_id": o["order_id"]}))
                        break
            if follow:
                return LLMResponse(text=None, tool_calls=follow)

        if (
            category == "returns_refunds"
            and order
            and _has(text, ["refund", "money back", "return it", "send it back", "return the"])
            and "create_refund_request" not in results
            and not _has(text, ["when will", "refund status"])
        ):
            amount = order["total"]
            for hint, name in ITEM_HINTS.items():
                if hint in text and name in order["item_prices"]:
                    amount = order["item_prices"][name]
                    break
            if not any("Blend" in i or "Ethiopia" in i for i in order["items"]):
                return LLMResponse(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            self._id(),
                            "create_refund_request",
                            {
                                "order_id": order["order_id"],
                                "amount": amount,
                                "reason": "customer requested return",
                            },
                        )
                    ],
                )

        return LLMResponse(text=None, tool_calls=[self._submit(ticket, raw, category, results, order)])

    def _submit(self, ticket: dict, raw: str, category: str, results: dict, order: dict | None):
        text = raw.lower()
        hits = results.get("search_help_center", {}).get("results", [])
        cust = results.get("lookup_customer", {})
        first = (cust.get("name") or "there").split()[0]
        top = hits[0] if hits else None

        lines = [f"Hi {first},", "", "Thanks for reaching out to Brewline."]
        if order:
            status = order["status"]
            if status == "shipped" and order.get("tracking_number"):
                lines.append(
                    f"Your order {order['order_id']} has shipped with {order['carrier']} "
                    f"(tracking {order['tracking_number']})."
                )
            elif status == "processing":
                lines.append(f"Your order {order['order_id']} hasn't shipped yet, so we can still update it.")
            elif status == "delivered":
                lines.append(f"I can see order {order['order_id']} was delivered on {order['delivered_at']}.")
        if top:
            lines.append(top["passage"])
        refund = results.get("create_refund_request")
        if refund:
            if refund.get("requires_human_approval"):
                lines.append(
                    f"I've opened a refund request for ${refund['amount']:.2f}; a teammate will confirm it shortly."
                )
            else:
                lines.append(f"I've started a refund of ${refund['amount']:.2f} for you.")
        lines += ["", "Best,", "Brewline Support"]

        consistent = bool(top) and _article_matches(top["slug"], category)
        args: dict[str, Any] = {
            "category": category,
            "priority": prioritize(text, category),
            "sentiment": sentiment(raw),
            "summary": ticket["subject"],
            "order_id": order["order_id"] if order else None,
            "draft_reply": "\n".join(lines),
            "citations": [top["slug"]] if top else [],
            "confidence": 0.85 if consistent else 0.6,
            "needs_human": False,
            "escalation_reason": None,
        }
        return ToolCall(self._id(), "submit_triage", args)


_ARTICLE_CATEGORY = {
    "shipping-times": "shipping",
    "track-order": "shipping",
    "change-address": "shipping",
    "returns-policy": "returns_refunds",
    "damaged-item": "product_issue",
    "warranty": "product_issue",
    "descaling": "product_issue",
    "grinder-calibration": "product_issue",
    "subscriptions": "subscription",
    "billing": "billing",
    "account": "account",
    "beans-freshness": "general",
}


def _article_matches(slug: str, category: str) -> bool:
    return _ARTICLE_CATEGORY.get(slug) == category
