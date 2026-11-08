import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def create(client, **kw):
    body = {
        "customer_email": "jordan.brooks@example.com",
        "subject": "Where is my grinder?",
        "body": "Order BL-48390, tracking hasn't moved.",
    }
    body.update(kw)
    r = client.post("/api/tickets", json=body)
    assert r.status_code == 202
    return r.json()["id"]


def test_health(client):
    assert client.get("/api/health").json()["provider"] == "offline"


def test_create_triages_in_background(client):
    tid = create(client)
    # TestClient runs background tasks before returning
    t = client.get(f"/api/tickets/{tid}").json()
    assert t["status"] in ("auto_resolved", "needs_review")
    assert t["triage"]["order_id"] == "BL-48390"
    assert t["trace"], "trace should be recorded"


def test_review_flow_with_edit(client):
    tid = create(
        client,
        customer_email="hannah.weber@example.com",
        subject="Refund",
        body="Please refund the unused grinder from BL-48120, I want to return it.",
    )
    t = client.get(f"/api/tickets/{tid}").json()
    assert t["status"] == "needs_review"
    assert t["refunds"][0]["status"] == "pending"

    r = client.post(f"/api/tickets/{tid}/approve", json={"reply": "Edited reply", "actor": "dana"})
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "sent"
    assert done["events"][-1]["action"] == "edited"
    assert done["refunds"][0]["status"] == "approved"

    assert client.post(f"/api/tickets/{tid}/approve", json={}).status_code == 409
    assert client.post(f"/api/tickets/{tid}/retriage").status_code == 409


def test_reject(client):
    tid = create(
        client,
        customer_email="emily.novak@example.com",
        subject="Sparks",
        body="My machine sparked when I turned it on",
    )
    t = client.get(f"/api/tickets/{tid}").json()
    assert t["priority"] == "urgent" and t["status"] == "needs_review"
    r = client.post(f"/api/tickets/{tid}/reject", json={"note": "calling the customer"})
    assert r.json()["status"] == "rejected"


def test_validation_and_404(client):
    bad = client.post("/api/tickets", json={"customer_email": "nope", "subject": "x", "body": "y"})
    assert bad.status_code == 422
    assert client.get("/api/tickets/missing").status_code == 404
    assert client.get("/api/articles/missing").status_code == 404


def test_list_filter_stats_and_demo(client):
    assert client.post("/api/demo/load?limit=5").json() == {"loaded": 5}
    all_tickets = client.get("/api/tickets").json()
    assert len(all_tickets) >= 5
    review = client.get("/api/tickets", params={"status": "needs_review"}).json()
    assert all(t["status"] == "needs_review" for t in review)
    s = client.get("/api/stats").json()
    assert s["triaged"] >= 5
    assert 0 <= s["auto_resolve_rate"] <= 1


def test_article(client):
    a = client.get("/api/articles/returns-policy").json()
    assert a["title"] == "Returns and refunds"
