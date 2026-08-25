# RevPulse — Architecture

```
                        MERCHANT (Biryani House)
                                │
              ┌─────────────────┴──────────────────┐
              ▼                                    ▼
        FIRST-PARTY REVIEWS                RAZORPAY TEST-MODE
        (feedback tied to orders)          TRANSACTIONS / CUSTOMERS
              │                                    │
              └─────────────────┬──────────────────┘
                                ▼
                        AI GROWTH AGENT
                 (Claude tool-calling loop, FastAPI)
              observe → reason → recommend → (approve) → act
                                │
                ┌───────────────┼────────────────┐
                ▼               ▼                ▼
         Review extraction  Insight engine   Action tools
         (per-review        (theme trends,   (create campaign,
          structured        time/zone conc., recovery offer,
          analysis, cached) revenue joins)   payment links, replies)
                                │
                                ▼
                      ██ POLICY ENGINE ██          ← deterministic Python,
                   (bounds, gates, caps —            NOT AI. The LLM can ask;
                    ALLOWED / NEEDS_APPROVAL /       only policy can permit.
                    BLOCKED)
                                │
                                ▼
                      RAZORPAY TEST-MODE API
                    (payment links, offer codes)
                                │
                                ▼
                  ██ AUDIT TRAIL (write-ahead) ██  → streams live to UI (WebSocket)
                                │
                                ▼
                    ATTRIBUTION + MEASUREMENT
              (unique link/code per campaign → exact,
               not statistical, revenue attribution)
```

## Components

### Agent loop — `backend/app/agent/loop.py`

The whole brain is ~40 lines, on the raw Anthropic SDK — no LangChain, no framework. Each model turn either returns text (done) or requests tool calls. For every call:

1. `policy.check(tool, args)` → verdict (deterministic, before anything happens)
2. `audit.write_ahead(...)` → durable log row with the agent's own reasoning attached, **before execution**
3. Execute only if `ALLOWED` (read/draft tools directly; action tools via `actions.py`); `NEEDS_APPROVAL` parks in the approval queue; `BLOCKED` returns the violated rule to the model as data
4. `audit.complete(...)` → outcome, Razorpay refs, errors

The model receives verdicts as tool results, so a refusal is something it can reason about and route around *compliantly* (see the graceful-failure demo).

### Tools — `backend/app/agent/tools.py`

- **Read-only (auto-allowed):** `get_reviews`, `get_review_stats`, `get_customers`, `get_customer_history`, `get_transactions`, `get_campaign_results`
- **Drafting (auto-allowed, nothing external):** `draft_reply(review_id, tone)`
- **Actions (always through policy):** `create_recovery_offer`, `create_campaign`, `create_payment_link`, `post_reply`

Aggregates are computed in SQL/Python (theme × month trends, time-of-day and zone concentration, LTV joins, repeat-rate comparisons with sample sizes) — the model reasons over aggregates; it does not free-associate over raw text.

### Extraction — `backend/app/agent/extraction.py`

One-time batched pass (20 reviews/call, cheap model) labeling each review with sentiment, themes from a fixed vocabulary, urgency, and a churn signal — cached in DB columns forever. Fixed vocabulary keeps clustering deterministic and cheap; the interactive agent never re-reads raw review text at scale.

### Policy engine — `backend/app/policy.py`

Pure functions over the DB; zero LLM involvement. Order of evaluation: BLOCKED rules (hard bounds, forbidden actions, customer protection, budget maths) → approval thresholds → allow. Offer values are estimated from the targeted customers' real average order values, so a 20% offer to a high-spend customer correctly escalates to a human while the same offer to a small customer auto-passes. Defense in depth: refund/payout/withdrawal "tools" don't exist, and the policy engine blocks them anyway if ever requested.

### Audit trail — `backend/app/audit.py`

`audit_log(id, ts, actor, tool, args_json, agent_reasoning, policy_verdict, policy_rule_hit, razorpay_ref, status, error, completed_ts)`. The row is committed **before** execution (write-ahead) and updated after — crashes and API failures still leave a record. Every write is broadcast over `/ws/audit` to the dashboard's live console.

### Money actions & idempotency — `backend/app/actions.py`, `backend/app/razorpay_client.py`

Every Razorpay call carries a deterministic idempotency key `sha256(tool + args + customer)`. Before calling Razorpay we check our own ledger for the key; a retry returns the existing link instead of creating a second one. The key is also sent as the payment link's `reference_id`, so even a race would hit Razorpay's uniqueness check. Webhook processing is idempotent the same way (a replayed `payment_link.paid` cannot double-attribute).

### Attribution — `backend/app/routers/actions_api.py`

Each campaign gets a unique offer code; each targeted customer gets their own payment link. `payment_link.paid` webhooks (or the local simulator, same code path) mark the link paid, write an attributed `Order` row carrying the `campaign_id`, and stamp the redemption. Campaign results (targeted / redeemed / revenue via links / incentive cost) are therefore exact joins, not estimates.

### Frontend — `frontend/`

React + Vite + Tailwind SPA: overview, issues with evidence drill-down, reply queue, revenue intelligence, action center (agent runs + approval queue + campaign results), and the live audit console fed by WebSocket.

## Scaling notes (1M reviews)

Extraction already runs as a batched offline pass — at scale it becomes a queue worker; the fixed theme vocabulary becomes embedding-based clustering with periodic re-labeling. SQLite swaps for Postgres (the schema is the design, not the engine). Aggregates move to materialized views. The agent layer is unchanged: it reasons over aggregates, so its token cost is independent of review volume.
