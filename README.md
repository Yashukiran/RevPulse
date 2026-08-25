# RevPulse — AI Growth Agent for Merchants

Businesses collect hundreds of reviews and almost none of that information ever becomes action. RevPulse reads a merchant's first-party reviews and Razorpay transaction data, finds what is costing them money, and turns it into revenue actions — recovery offers, win-back campaigns, one-click review replies — **with every money action explainable, bounded, gated, and audited.**

The agent is the product, not a chatbot bolted onto a dashboard. Nobody asks it anything: it scans on its own, surfaces an opportunity with the evidence behind it, states what the action is worth and the most it can cost, and waits for the merchant to approve.

## The autonomous loop

```
detection                 two independent signals, deliberately not one:
                          · BEHAVIOUR — a valuable regular has gone silent for far
                            longer than their own ordering rhythm (transactions
                            only; works for every customer, no review needed)
                          · WORDS — a high-value customer's own review says they
                            are leaving (explains WHY, and shapes the message)
        ↓
opportunity               evidence + lifetime value at risk + realistically recoverable
                          + expected return + MAXIMUM EXPOSURE
        ↓
policy engine             deterministic bounds; agent-initiated proposals always escalate
        ↓
merchant approval         the human gate — nothing moves without it
        ↓
Razorpay test mode        unique payment link / order + unique offer code per customer
        ↓
payment webhook           revenue attributed back to the opportunity that caused it
        ↓
holdout comparison        a share of the segment gets no offer, so return rates can be
                          compared — attribution says the payment came through us,
                          only a control group speaks to whether we caused it
        ↓
audit trail               every step written before it happened, streamed live to the UI
```

One command proves the whole chain, repeatably: `python scripts/test_agent_loop.py`.

Two rules make this defensible rather than a demo trick:

1. **Every rupee figure is computed in Python from the merchant's own data.** The model writes the explanation and never the arithmetic, so it cannot invent a number.
2. **The four money figures are kept distinct, and none of them oversells.** Lifetime value at risk is what these customers have already spent — context for how much the relationship is worth, not money the offer can recover. Realistically recoverable is what one returning order from each is worth. Expected recovered is a projection with its assumption printed beside it. Maximum exposure is exact: what the offer costs if every customer redeems.

Built for the Razorpay AI Buildathon, Track 01 (AI Growth & Agentic Commerce). Demo merchant: *Biryani House*, a fictional Bengaluru delivery restaurant.

## The core safety principle

**The LLM never touches Razorpay.** It can only *request* tools. Every money-touching request passes through a deterministic Python policy engine (not AI) that returns `ALLOWED`, `NEEDS_APPROVAL`, or `BLOCKED` — and is written to a write-ahead audit log *before* execution, so even failures leave a record. Attribution is exact, not statistical: every campaign gets a unique offer code and unique Razorpay payment links, so every resulting payment is attributable by construction.

```
reviews + transactions → agent (Claude tool-calling) → POLICY ENGINE → Razorpay test API
                                                     ↘ AUDIT TRAIL (write-ahead, streams live to UI)
                                                        → exact attribution per campaign
```

## Policy engine rules (deterministic, in code — `backend/app/policy.py`)

| Rule | Bound |
|---|---|
| Max discount | 20% |
| Max recovery offer value | ₹300 per customer |
| Daily incentive budget | ₹5,000 |
| Per-campaign cap | ₹2,000 |
| Needs merchant approval | any campaign · any offer > ₹150 · any segment > 25 customers · posting any reply publicly |
| Always blocked | refunds · withdrawals · payout changes · exceeding budget · more than 1 offer per customer per 30 days · re-targeting customers who already redeemed |
| Agent-initiated proposals | always escalate to the merchant, even when every other bound is clear (`PROACTIVE_REQUIRES_APPROVAL`) |
| Idempotency | every Razorpay call carries an idempotency key — a retry can never double-create or double-charge |

Customer-protection bounds (frequency cap, dedupe) are enforced as strictly as money bounds.

## Features

0. **The growth agent (the product)** — scans transaction *behaviour* (the primary signal, available for 100% of customers) and feedback *language* (the enrichment layer, which explains why) unprompted, raises opportunities with evidence, money maths and a policy verdict already attached, executes on approval, and measures the result. It rescans automatically when new feedback carries a churn signal.
1. **Review intelligence** — what customers love/hate, theme trends, time-of-day and zone concentration
2. **Issue & opportunity detection** — clustered recurring problems with click-through to the underlying evidence (actual reviews)
3. **Reply queue** — urgent/important/routine triage, AI-drafted replies in 3 tones; posting is a gated action
4. **Revenue intelligence** — joins reviews ↔ transactions: *"customers mentioning slow service repeat at 8% vs 44% baseline (n=86 vs n=206)"* — always shown as association with sample sizes, never causation
5. **Action agent** — recommends and, on approval, executes recovery offers and campaigns as real Razorpay test-mode payment links with unique codes → exact attribution; live audit console streams every step

## Evaluation

`scripts/evaluate.py` scores the system against planted ground truth (`data/ground_truth.json`) and writes [EVALUATION.md](EVALUATION.md) — including failures and false positives. Current results: 5/5 planted patterns detected, 0/2 decoy false positives, 3/3 at-risk customers found, 100/100 policy verdicts correct, **0 unauthorized money actions**, failure-injection + idempotency proof passing.

`scripts/demo_failure.py` reproduces the graceful-failure path: an over-budget ₹2,000 campaign is blocked by policy, the agent explains why in plain language, proposes a compliant ₹1,200 alternative into the approval queue, and the idempotency ledger proves the retry created zero duplicates.

## Setup

Prereqs: Python 3.11+, Node 18+, a Razorpay account (test mode), an Anthropic API key.

```bash
git clone <this repo> && cd <repo>

# backend
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows (use .venv/bin/pip elsewhere)
cp ../.env.example .env                            # then fill in your keys

# data (seeded, deterministic)
cd ..
backend/.venv/Scripts/python scripts/generate_data.py
backend/.venv/Scripts/python -m app.agent.extraction   # one-time review labeling (run from backend/)

# run
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000
cd frontend && npm install && npm run dev              # http://localhost:5173
```

Tests: `scripts/test_policy.py` (adversarial policy cases), `scripts/test_holdout.py` (control-group split and incrementality), `scripts/test_money_chain.py` (full Razorpay chain incl. idempotency), `scripts/evaluate.py` (full harness), `scripts/test_agent.py` (agent surfaces planted insights). They build their own fixtures and restore state, so they can be re-run in any order without affecting demo data.

Demo prep: `scripts/reset_demo.py` clears campaigns and the audit trail while keeping reviews and their cached labels; `scripts/seed_demo.py` then creates one recovery campaign with real test-mode links and marks two redeemed.

**Razorpay test-mode limit:** an account may hold only 30 payment links. `evaluate.py` therefore stubs the provider call by default (everything it measures — audit, ledger, idempotency — is our code); run it with `EVAL_LIVE=1` to hit the live API, and use `test_money_chain.py` for the live end-to-end proof.

## Data — the honest story

There is no external dataset. `scripts/generate_data.py` (seeded RNG, committed) creates ~300 customers, 8 months of orders, and ~785 reviews with planted, answer-keyed patterns — plus decoys that must *not* be flagged. Everything money-shaped (orders, payment links, payments, webhooks) goes through the actual Razorpay test-mode API.

**Where do reviews come from in production?** First-party feedback collected at the payment moment: after each successful Razorpay payment the customer gets a feedback link tied to that transaction. That links every review to a customer and an order by construction — which is what makes review↔revenue joins possible at all (public platform reviews are anonymous and unmatchable).

## Limitations

The short version is below; [DEFENSE.md](DEFENSE.md) states the limits in full — cannibalisation, cold start, why a restaurant is the demo rather than the best vertical, when a discount is the wrong intervention, messaging compliance, and what breaks at scale.

- Synthetic, seeded data (patterns are planted; the answer key is committed)
- Single merchant, demo login only
- Campaign customer responses are **simulated** and labeled as such everywhere
- Review labeling quality is bounded by the extraction model
- Associations are never presented as causation

## Stack

FastAPI + SQLAlchemy/SQLite · Claude tool-calling (raw SDK, no agent framework — the loop is ~40 lines in `backend/app/agent/loop.py`) · Razorpay Python SDK (test mode) · React + Vite + Tailwind · WebSocket for the live audit console.
