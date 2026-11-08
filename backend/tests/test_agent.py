from app import services
from app.agent import run_agent
from app.db import Ticket

from .conftest import ScriptedProvider, submit


def make_ticket(
    session,
    email="jordan.brooks@example.com",
    subject="Where is my grinder?",
    body="Order BL-48390 hasn't arrived",
):
    return services.create_ticket(session, email, subject, body)


def test_full_tool_loop_produces_grounded_triage(session, cfg):
    t = make_ticket(session)
    provider = ScriptedProvider(
        [
            [("lookup_customer", {"email": t.customer_email}), ("get_order", {"order_id": "BL-48390"})],
            [("search_help_center", {"query": "tracking not updating"})],
            [submit(order_id="BL-48390", citations=["track-order"])],
        ]
    )
    r = run_agent(session, t, provider, cfg)
    assert r.finished
    assert r.output.order_id == "BL-48390"
    assert r.output.citations == ["track-order"]
    assert not r.needs_human
    assert r.input_tokens == 300
    tools = [s["tool"] for s in r.trace if s["type"] == "tool"]
    assert tools == ["lookup_customer", "get_order", "search_help_center", "submit_triage"]


def test_citing_unretrieved_article_is_stripped_and_escalated(session, cfg):
    t = make_ticket(session)
    provider = ScriptedProvider([[submit(citations=["warranty"])]])
    r = run_agent(session, t, provider, cfg)
    assert r.output.citations == []
    assert r.needs_human
    assert any("never retrieved" in x for x in r.escalation_reasons)


def test_order_id_must_be_looked_up_or_in_ticket(session, cfg):
    t = make_ticket(session, body="my grinder hasn't arrived")
    r = run_agent(session, t, ScriptedProvider([[submit(order_id="BL-48390")]]), cfg)
    assert r.output.order_id is None
    assert any("without looking it up" in x for x in r.escalation_reasons)


def test_invalid_submission_gets_feedback_then_retries(session, cfg):
    t = make_ticket(session)
    provider = ScriptedProvider(
        [
            [submit(category="logistics")],
            [submit()],
        ]
    )
    r = run_agent(session, t, provider, cfg)
    assert r.finished and r.output.category == "shipping"
    first_result = [s for s in r.trace if s["type"] == "tool"][0]["result"]
    assert "invalid submission" in first_result["error"]


def test_cannot_read_another_customers_order(session, cfg):
    t = make_ticket(session, email="maya.chen@example.com", body="what about BL-48390?")
    provider = ScriptedProvider([[("get_order", {"order_id": "BL-48390"})], [submit()]])
    r = run_agent(session, t, provider, cfg)
    result = [s for s in r.trace if s.get("tool") == "get_order"][0]["result"]
    assert "does not belong" in result["error"]


def test_refund_requires_order_lookup_first(session, cfg):
    t = make_ticket(session, email="hannah.weber@example.com", body="refund BL-48120")
    provider = ScriptedProvider(
        [
            [("create_refund_request", {"order_id": "BL-48120", "amount": 229, "reason": "x"})],
            [submit(category="returns_refunds")],
        ]
    )
    r = run_agent(session, t, provider, cfg)
    result = [s for s in r.trace if s.get("tool") == "create_refund_request"][0]["result"]
    assert "get_order" in result["error"]


def test_large_refund_routes_to_human(session, cfg):
    t = make_ticket(session, email="hannah.weber@example.com", body="refund the grinder from BL-48120")
    provider = ScriptedProvider(
        [
            [("get_order", {"order_id": "BL-48120"})],
            [("create_refund_request", {"order_id": "BL-48120", "amount": 229, "reason": "unused"})],
            [submit(category="returns_refunds", order_id="BL-48120")],
        ]
    )
    r = run_agent(session, t, provider, cfg)
    assert r.needs_human
    assert any("exceeds" in x for x in r.escalation_reasons)


def test_unknown_tool_and_step_limit(session, cfg):
    t = make_ticket(session)
    provider = ScriptedProvider([[("delete_database", {})]] * 20)
    r = run_agent(session, t, provider, cfg)
    assert not r.finished
    assert r.needs_human
    assert r.output.confidence == 0.0
    assert "unknown tool" in r.trace[1]["result"]["error"]


def test_model_that_never_calls_tools_is_nudged_then_stops(session, cfg):
    t = make_ticket(session)
    provider = ScriptedProvider([])
    r = run_agent(session, t, provider, cfg)
    assert not r.finished
    assert len(provider.seen) == 2
    assert "submit_triage" in provider.seen[1][-1]["content"]


def test_triage_service_sets_statuses(session, cfg):
    t = make_ticket(session)
    provider = ScriptedProvider(
        [
            [("search_help_center", {"query": "tracking"})],
            [submit(citations=["track-order"])],
        ]
    )
    t = services.triage_ticket(session, t.id, provider, cfg)
    assert t.status == "auto_resolved"
    assert t.events[0].action == "auto_sent"

    t2 = services.triage_ticket(session, t.id, ScriptedProvider([[submit(confidence=0.3)]]), cfg)
    assert t2.status == "needs_review"
    assert session.query(Ticket).count() == 1


def test_provider_crash_marks_ticket_failed(session, cfg):
    class Boom:
        name, model = "boom", "boom"

        def chat(self, *a):
            raise RuntimeError("API down")

    t = make_ticket(session)
    t = services.triage_ticket(session, t.id, Boom(), cfg)
    assert t.status == "failed"
    assert "API down" in t.error
