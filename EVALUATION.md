# RevPulse — Evaluation Report

_Behind every number below is a reproducible script (`scripts/evaluate.py`, run 2026-08-25 08:57 UTC). Failures and false positives are reported, not hidden._

## 1. Insight detection (planted patterns P1–P5)

- **P1 slow-service cluster**: DETECTED — monthly counts [4, 6, 8, 10, 13, 17, 29], top time slot “Fri 7-10PM”
- **P2 hero product (biryani)**: DETECTED — praised in 302/432 positive reviews (70%; planted 70%)
- **P3 high-LTV churn risks**: DETECTED — 3/3 planted customers found, 0 false positives at the LTV>₹15k threshold
- **P4 packaging↔zone**: DETECTED — 28/35 complaints in Whitefield (80%; planted 80% in Whitefield)
- **P5 repeat-rate association**: DETECTED — slow-service reviewers 8.0% (n=87) vs others 44.2% (n=208) — association, not causation

**Recall: 5/5 planted patterns detected.**

**Decoy check (must NOT be flagged):**
- “parking complaints” (4 mentions): correctly not flagged (only 4 reviews, flat trend, no growth, no concentration)
- “spice-level comments” (16 mentions): correctly not flagged (scattered across months and zones, no trend, mild ratings)

**Decoy false positives: 0/2.**

## 2. Churn flagging

- Planted at-risk (LTV>₹15k + churn review): **3/3 found**
- Total customers with churn-signal reviews: 60 — the extraction model flags churn language broadly (e.g. slow-service complainers who say they 'almost gave up'). At the recovery-targeting threshold (LTV>₹15k) this reduces to the 3 planted customers with 0 false alarms.

## 3. Policy compliance (N=100 scripted + adversarial requests)

- Requests: **100** (legitimate, approval-tier, and adversarial —
  over-discount, over-budget, refunds, payout changes, frequency violations, negative amounts, unknown tools)
- Correct verdicts: **100/100** (55 allowed, 15 escalated, 30 blocked)
- **Unauthorized money actions: 0** (target 0)

## 4. Failure handling & idempotency (injected Razorpay failure)

- Injected failure on first Razorpay call: failure recorded, no crash
- Retry after failure: succeeded
- Ledger rows for the idempotency key: **1** (must be 1 — no double-create)
- Provider call: stubbed (set EVAL_LIVE=1 for live) — Razorpay test mode caps an account at 30 payment links, so this harness stays re-runnable; `scripts/test_money_chain.py` proves the same chain against the live API.

## 4b. Autonomous opportunity loop (detect → propose → gate)

- Unprompted scan surfaced **3 at-risk customer(s)**, 3/3 of them the planted high-LTV churn cohort
- Revenue at risk quantified from transactions: **₹79,090**
- Maximum financial exposure: **₹409** — within the ₹300/customer cap
- Proposed action gated before the merchant saw it: **NEEDS_APPROVAL** (agent-initiated: proposals the agent raises on its own always require merchant approval)
- Every figure above is computed in Python from the merchant's own data; the model only writes the explanation, so it cannot invent a rupee value.
- End-to-end loop (approve → Razorpay → webhook → attribution → audit) is proven separately and repeatably by `scripts/test_agent_loop.py`.

## 5. Campaign outcome simulation — **SIMULATED**

_Customer responses below are **simulated** with seeded probabilities (redemption chance scales with discount). No claim is made about real customer behaviour; in production these numbers come from actual webhook attributions._
- 10% offer to 20 customers → 4 redemptions (simulated p=0.22), revenue via links ₹1,620, incentive cost ₹900, net ₹720 **[SIMULATED]**
- 15% offer to 25 customers → 9 redemptions (simulated p=0.28), revenue via links ₹3,438, incentive cost ₹1,675, net ₹1,763 **[SIMULATED]**

## Summary

| Check | Result | Target |
|---|---|---|
| Planted-pattern recall | 5/5 | 5/5 |
| Decoy false positives | 0/2 | 0/2 |
| High-LTV churn customers | 3/3 (+0 false alarms) | 3/3 |
| Policy verdicts correct | 100/100 | 100 |
| Unauthorized money actions | 0 | 0 |
| Failure recovery + idempotency | PASS | PASS |
| Autonomous loop: detect + quantify + gate | PASS | PASS |

**Limitations:** synthetic seeded data; single merchant; campaign responses simulated; extraction quality bounded by the labeling model. Associations are never presented as causation.