# RevPulse — Evaluation Report

_Behind every number below is a reproducible script (`scripts/evaluate.py`, run 2026-08-25 17:53 UTC). Failures and false positives are reported, not hidden._

## 1. Insight detection (planted patterns P1–P5)

- **P1 slow-service cluster**: DETECTED — monthly counts [4, 6, 8, 10, 13, 17, 29], top time slot “Fri 7-10PM”
- **P2 hero product (biryani)**: DETECTED — praised in 302/432 positive reviews (70%; planted 70%)
- **P3 high-LTV churn risks**: DETECTED — 3/3 planted customers found, 0 false positives at the LTV>₹15k threshold
- **P4 packaging↔zone**: DETECTED — 28/35 complaints in Whitefield (80%; planted 80% in Whitefield)
- **P5 repeat-rate association**: DETECTED — slow-service reviewers 9.2% (n=87) vs others 44.2% (n=208) — association, not causation

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

- No open opportunity at scan time (all at-risk customers already have a live offer — the frequency cap is doing its job).
- End-to-end loop (approve → Razorpay → webhook → attribution → audit) is proven separately and repeatably by `scripts/test_agent_loop.py`.

- **Behavioural detector (no reviews, no model):** surfaced **10 lapsed high-value customer(s)** from transaction history alone — e.g. Neha Hegde, 7 orders roughly every 12 days, now silent for 129 days (10.3x their own rhythm)
- Lifetime value at risk **₹65,410**, realistically recoverable **₹8,254** (one returning order each), maximum exposure **₹1,455** — within the per-customer cap
- Gated before the merchant saw it: **NEEDS_APPROVAL**
- This detector covers customers who never wrote a review, which is most of them: reviews exist for a minority, transaction behaviour for everyone.

## 4c. Incrementality — control group

- Campaigns of **6+ customers** hold back **30%** as a control group: same profile, no offer, no link.
- The split is seeded off the campaign id, so it is reproducible and cannot be re-rolled until the numbers improve (verified: deterministic).
- Return rates are compared across both groups over a 30-day window, counting **any** order rather than only ones through our links — a control customer has no link, and a treated customer who returns by another route still returned.
- Segments below 6 skip the holdout and record why. A control group of two proves nothing.

**Limits of this measure, stated plainly:** attribution (a payment arrived through our link) is exact by construction. Incrementality (the offer *caused* a return that would not otherwise have happened) is not, and at the sample sizes a single merchant produces it never reaches statistical significance. Every lift figure is therefore labelled directional and shown with both group sizes. `scripts/test_holdout.py` proves the mechanism: deterministic split, control customers receive no link or offer record, and unfavourable results are reported rather than suppressed.

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
| Behavioural detector (no reviews needed) | PASS | PASS |
| Holdout split deterministic + control unoffered | PASS | PASS |

**Limitations:** synthetic seeded data; single merchant; campaign responses simulated; extraction quality bounded by the labeling model. Associations are never presented as causation.