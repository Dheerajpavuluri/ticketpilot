"""Score the agent against the labeled ticket set.

    python -m evals.run_evals --provider offline
    OPENAI_API_KEY=... python -m evals.run_evals --provider openai --concurrency 4

Writes evals/results/<provider>-<model>.{json,md}.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app import services
from app.config import settings
from app.db import init_db, make_engine
from app.llm import get_provider
from app.policy import PRIORITY_RANK

HERE = Path(__file__).parent
DATASET = HERE / "dataset.jsonl"
RESULTS = HERE / "results"
# dataset dates are written relative to this day
EVAL_TODAY = "2026-11-06"


def load_dataset(limit: int | None) -> list[dict]:
    rows = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    return rows[:limit] if limit else rows


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, max(0, round(p / 100 * (len(s) - 1))))
    return s[k]


def run(provider_name: str, limit: int | None, concurrency: int) -> dict:
    cfg = replace(settings, llm_provider=provider_name, today_override=EVAL_TODAY)
    rows = load_dataset(limit)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    engine = make_engine(f"sqlite:///{tmp.name}")
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    init_db(engine, factory)

    def one(row: dict) -> dict:
        provider = get_provider(cfg, provider_name)
        with factory() as session:
            t = services.create_ticket(session, row["customer_email"], row["subject"], row["body"])
            t0 = time.perf_counter()
            t = services.triage_ticket(session, t.id, provider, cfg)
            wall = (time.perf_counter() - t0) * 1000
            tr = t.triage
            return {
                "id": row["id"],
                "subject": row["subject"],
                "expected": row["expected"],
                "status": t.status,
                "error": t.error,
                "got": None
                if tr is None
                else {
                    "category": tr.category,
                    "priority": tr.priority,
                    "needs_human": tr.needs_human,
                    "order_id": tr.order_id,
                    "citations": tr.citations,
                    "confidence": tr.confidence,
                    "reasons": tr.escalation_reasons,
                    "input_tokens": tr.input_tokens,
                    "output_tokens": tr.output_tokens,
                },
                "latency_ms": round(wall),
                "model": provider.model,
            }

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        results = list(pool.map(one, rows))
    engine.dispose()
    os.unlink(tmp.name)
    return score(provider_name, results)


def score(provider_name: str, results: list[dict]) -> dict:
    ok = [r for r in results if r["got"]]
    n = len(ok)
    cat = sum(r["got"]["category"] == r["expected"]["category"] for r in ok)
    prio = sum(r["got"]["priority"] == r["expected"]["priority"] for r in ok)
    prio1 = sum(abs(PRIORITY_RANK[r["got"]["priority"]] - PRIORITY_RANK[r["expected"]["priority"]]) <= 1 for r in ok)
    tp = sum(r["got"]["needs_human"] and r["expected"]["needs_human"] for r in ok)
    fp = sum(r["got"]["needs_human"] and not r["expected"]["needs_human"] for r in ok)
    fn = sum(not r["got"]["needs_human"] and r["expected"]["needs_human"] for r in ok)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None

    with_order = [r for r in ok if r["expected"]["order_id"]]
    order_hits = sum(r["got"]["order_id"] == r["expected"]["order_id"] for r in with_order)
    with_article = [r for r in ok if r["expected"]["article"]]
    cite_hits = sum(r["expected"]["article"] in r["got"]["citations"] for r in with_article)
    grounding = sum(any("never retrieved" in x or "without looking" in x for x in r["got"]["reasons"]) for r in ok)
    auto = sum(not r["got"]["needs_human"] for r in ok)
    lat = [r["latency_ms"] for r in ok]

    summary = {
        "provider": provider_name,
        "model": results[0]["model"] if results else None,
        "tickets": len(results),
        "failed_runs": len(results) - n,
        "category_accuracy": pct(cat, n),
        "priority_accuracy": pct(prio, n),
        "priority_within_one": pct(prio1, n),
        "escalation_precision": round(100 * precision, 1) if precision is not None else None,
        "escalation_recall": round(100 * recall, 1) if recall is not None else None,
        "escalation_f1": round(100 * f1, 1) if f1 is not None else None,
        "unsafe_auto_replies": fn,
        "order_id_accuracy": pct(order_hits, len(with_order)),
        "citation_hit_rate": pct(cite_hits, len(with_article)),
        "grounding_violations": grounding,
        "auto_resolve_rate": pct(auto, n),
        "latency_p50_ms": percentile(lat, 50),
        "latency_p95_ms": percentile(lat, 95),
        "avg_tokens": round(statistics.mean(r["got"]["input_tokens"] + r["got"]["output_tokens"] for r in ok))
        if ok
        else 0,
    }
    misses = [
        {
            "id": r["id"],
            "subject": r["subject"],
            "expected": {k: r["expected"][k] for k in ("category", "priority", "needs_human")},
            "got": {k: r["got"][k] for k in ("category", "priority", "needs_human")} if r["got"] else None,
            "error": r["error"],
        }
        for r in results
        if not r["got"]
        or r["got"]["category"] != r["expected"]["category"]
        or r["got"]["needs_human"] != r["expected"]["needs_human"]
    ]
    return {"summary": summary, "misses": misses, "results": results}


def to_markdown(report: dict) -> str:
    s = report["summary"]
    rows = [
        ("Category accuracy", f"{s['category_accuracy']}%"),
        (
            "Priority accuracy (exact / within one level)",
            f"{s['priority_accuracy']}% / {s['priority_within_one']}%",
        ),
        ("Escalation precision / recall", f"{s['escalation_precision']}% / {s['escalation_recall']}%"),
        ("Unsafe auto-replies (should have gone to a human)", str(s["unsafe_auto_replies"])),
        ("Order ID accuracy", f"{s['order_id_accuracy']}%"),
        ("Citation hit rate (expected article cited)", f"{s['citation_hit_rate']}%"),
        ("Grounding violations", str(s["grounding_violations"])),
        ("Auto-resolve rate", f"{s['auto_resolve_rate']}%"),
        ("Latency p50 / p95", f"{s['latency_p50_ms']:.0f} ms / {s['latency_p95_ms']:.0f} ms"),
        ("Avg tokens per ticket", str(s["avg_tokens"])),
    ]
    out = [
        f"# Eval: {s['provider']} / {s['model']}",
        "",
        f"{s['tickets']} tickets, {s['failed_runs']} failed runs",
        "",
    ]
    out += ["| Metric | Result |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows]
    if report["misses"]:
        out += ["", "## Misses", "", "| Ticket | Expected | Got |", "|---|---|---|"]
        for m in report["misses"]:
            e, g = m["expected"], m["got"]
            got = f"{g['category']}, {g['priority']}, human={g['needs_human']}" if g else f"error: {m['error']}"
            out.append(
                f"| {m['id']} {m['subject']} | {e['category']}, {e['priority']}, human={e['needs_human']} | {got} |"
            )
    return "\n".join(out) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default=settings.llm_provider, choices=["offline", "openai", "anthropic"])
    p.add_argument("--limit", type=int)
    p.add_argument("--concurrency", type=int, default=1)
    args = p.parse_args()

    report = run(args.provider, args.limit, args.concurrency)
    RESULTS.mkdir(exist_ok=True)
    s = report["summary"]
    stem = f"{s['provider']}-{s['model']}".replace("/", "_")
    (RESULTS / f"{stem}.json").write_text(json.dumps(report, indent=2, default=str))
    md = to_markdown(report)
    (RESULTS / f"{stem}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
