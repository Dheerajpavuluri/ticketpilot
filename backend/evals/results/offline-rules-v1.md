# Eval: offline / rules-v1

36 tickets, 0 failed runs

| Metric | Result |
|---|---|
| Category accuracy | 88.9% |
| Priority accuracy (exact / within one level) | 80.6% / 100.0% |
| Escalation precision / recall | 43.8% / 100.0% |
| Unsafe auto-replies (should have gone to a human) | 0 |
| Order ID accuracy | 95.8% |
| Citation hit rate (expected article cited) | 74.3% |
| Grounding violations | 0 |
| Auto-resolve rate | 55.6% |
| Latency p50 / p95 | 8 ms / 10 ms |
| Avg tokens per ticket | 0 |

## Misses

| Ticket | Expected | Got |
|---|---|---|
| T-004 Beans taste stale | returns_refunds, medium, human=False | returns_refunds, medium, human=True |
| T-006 Cancel my order | shipping, medium, human=False | shipping, medium, human=True |
| T-008 Kettle not heating | product_issue, high, human=False | product_issue, high, human=True |
| T-011 Charged after canceling | subscription, medium, human=False | billing, low, human=True |
| T-013 Refund status | returns_refunds, medium, human=False | returns_refunds, medium, human=True |
| T-016 Tracking for descaler | shipping, low, human=False | product_issue, medium, human=False |
| T-028 Wrong beans in box | product_issue, medium, human=False | subscription, medium, human=True |
| T-033 Update payment method | account, low, human=False | billing, low, human=True |
| T-034 Wrong kettle color | returns_refunds, low, human=False | returns_refunds, medium, human=True |
| T-036 Hi | general, low, human=False | general, low, human=True |
