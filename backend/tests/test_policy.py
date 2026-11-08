from app.policy import apply_policy


def run(cfg, text="where is my order", **kw):
    args = dict(
        text=text,
        priority="low",
        model_needs_human=False,
        model_reason=None,
        confidence=0.95,
        refund_amounts=[],
        grounding_issues=[],
        cfg=cfg,
    )
    args.update(kw)
    return apply_policy(**args)


def test_clean_ticket_auto_resolves(cfg):
    r = run(cfg)
    assert not r.needs_human and r.reasons == []


def test_safety_forces_urgent_and_human(cfg):
    r = run(cfg, text="I saw sparks coming out of the back")
    assert r.needs_human and r.priority == "urgent"


def test_legal_raises_to_high(cfg):
    r = run(cfg, text="I'm talking to my lawyer")
    assert r.needs_human and r.priority == "high"


def test_policy_never_lowers_priority(cfg):
    r = run(cfg, text="I opened a chargeback", priority="urgent")
    assert r.priority == "urgent"


def test_large_refund_needs_approval(cfg):
    assert run(cfg, refund_amounts=[229.0]).needs_human
    assert not run(cfg, refund_amounts=[89.0]).needs_human


def test_low_confidence_escalates(cfg):
    r = run(cfg, confidence=0.4)
    assert r.needs_human and "low confidence" in r.reasons[0]


def test_account_deletion_escalates(cfg):
    assert run(cfg, text="please delete my account and data").needs_human


def test_model_request_is_kept(cfg):
    r = run(cfg, model_needs_human=True, model_reason="unclear request")
    assert r.reasons == ["model: unclear request"]
