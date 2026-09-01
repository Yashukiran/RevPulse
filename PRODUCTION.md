# Taking RevPulse to a real merchant

What I would need from them, what data it comes from, what has to be built, and the order I would do it in.

The demo runs on synthetic data and a single merchant with no authentication. This document is the honest path from that to a real business using it — including the two places where the answer is *"that does not work yet, and here is why."*

---

## Part 1 — What I need from the merchant

Six things, in the order I would ask for them.

### 1 · Access to their Razorpay account — read *and* write

Read to pull their history, write to create offers.

**The right way: Razorpay OAuth.** The merchant authorises RevPulse from their own dashboard and I receive a scoped access token. They can revoke it at any time, and I never hold their secret key. This is how a partner integration should work.

**The fallback: they generate API keys** in Dashboard → Account & Settings → API Keys and paste them into onboarding. Simpler, and what a small tool usually does — but it means holding a credential that can move their money, so it goes straight into a secrets manager (AWS KMS / GCP Secret Manager), encrypted at rest, never in the application database, never in a log line.

**Start in test mode.** Every integration step below is done against their *test* keys first. Live keys come only after shadow mode passes.

### 2 · A registered webhook, and its secret

So payments reach RevPulse the moment they happen. Registered on their account (by them, or by me via the API) pointing at `https://…/webhooks/razorpay`, subscribed to `payment.captured`, `payment_link.paid` and `payment.failed`.

The webhook secret is required — `verify_webhook_signature()` rejects anything unsigned, and it must, or anyone could post a fake "paid" event and pollute their revenue figures.

### 3 · Written consent to process their customers' data

Not optional and not a formality. Under the **DPDP Act** the merchant is the data fiduciary and RevPulse is a processor, so we need a **data processing agreement** covering purpose, retention, deletion on request, and breach notification.

Also required before a single message is sent: **consent to be contacted**, an honoured opt-out, and — for promotional SMS — **DLT registration** of sender header and template. None of that exists in the demo, which is why notification is switched off entirely today.

### 4 · A line-item data source — or an honest downgrade

**This is the first real gap.** Razorpay tells me a payment was ₹840. It does not tell me it was one Mutton Dum Biryani and two naan.

Item-level demand forecasting — the *"prepare 17 more of this specific item"* output — needs a basket. So one of:

- **Their POS or ordering system**, integrated (Petpooja, Posist, Shopify, WooCommerce, a custom backend). Best answer, most work.
- **Line items in the Razorpay `notes` field**, if their checkout can be made to send them. Cheap, requires a change on their side.
- **Neither** — and then I say so plainly: demand planning still predicts *order volume* for the busy window, which is genuinely useful for staffing, but the item breakdown is switched off rather than guessed.

I would rather ship the feature degraded and labelled than invent a basket.

### 5 · Their actual business rules

Every bound in the demo is a constant I chose: 20% max discount, ₹300 per customer, ₹5,000 a day, ₹2,000 per campaign. A real merchant's numbers are their own, and depend on their margin. These move from module constants into a per-merchant configuration table, set during onboarding and changeable only by the owner — never by the agent.

### 6 · A named human who approves

The whole design assumes someone clicks approve. That person needs to exist, have a login, and understand that they are authorising real money. If nobody will look at the queue daily, the product does not work and should not be sold to them.

---

## Part 2 — What data comes from where

| RevPulse table | Source | Notes |
|---|---|---|
| `merchants` | Onboarding form | Name, city, category, timezone |
| `customers` | `GET /v1/customers` + the `email` / `contact` on each payment | **The critical one — see below** |
| `orders` | `GET /v1/payments` (paginated), joined to `GET /v1/orders` | `amount` ÷ 100 for rupees, `created_at` for `ts` |
| `orders.items_json` | **Not available from Razorpay.** POS integration, or `notes`, or disabled | The gap from §4 above |
| `reviews` | **Does not exist yet.** Must be collected from zero | See Phase 4 |
| `payment_links`, `campaigns`, `offer_redemptions`, `budget_spend`, `audit_log`, `opportunities`, `demand_plans` | Created by RevPulse itself | No import needed |

### The critical unknown: how many payments carry an identity

Everything in this product depends on knowing *which customer* a payment belongs to. `create_payment_link()` requires a name, an email **and** a phone. A payment with none of those is revenue I can see but a customer I cannot recover.

**So the very first thing I run is a measurement, not a feature:**

```
pull 6-12 months of payments
→ what % have an email or a contact number?
→ how many distinct identified customers?
→ how many of those have 5+ orders (the minimum for a rhythm)?
```

That number decides whether this merchant is a customer at all. If 80% of their volume is anonymous UPI QR scans — common in Indian restaurants, and stated in [DEFENSE.md](DEFENSE.md) — I tell them the win-back half will only ever see a fifth of their business, and let them decide. **The measurement is the honest pitch.**

---

## Part 3 — The technical steps, in order

### Phase 1 · Make it multi-tenant and authenticated *(must happen first)*

Nothing else is safe until this is done.

- **Authentication.** There is none today. Email + password with a proper hash, or Google SSO. Sessions, CSRF, rate limiting on the login.
- **`merchant_id` on every table.** Today only `customers` and `menu_items` have it. Every other table needs it, and every query needs to filter on it.
- **Postgres row-level security**, so tenant isolation is enforced by the database rather than by remembering a `WHERE` clause. One missed filter otherwise leaks merchant A's customers into merchant B's dashboard.
- **Postgres instead of SQLite** — the concurrent, transactional foundation this needs. The schema is already engine-agnostic; see the README.
- **Credentials in a secrets manager**, encrypted, per merchant.

### Phase 2 · Backfill their history

A background job, because it is tens of thousands of API calls:

1. Page through `GET /v1/payments` from the earliest date available (`count`/`skip`, 100 per page, respecting rate limits).
2. For each captured payment: upsert a `customers` row keyed on the strongest identity available — Razorpay `customer_id` if present, else a normalised email, else a normalised phone.
3. Insert an `orders` row: `amount ÷ 100`, `created_at`, and the basket if a POS source exists.
4. Store a cursor so the job is **resumable** — a backfill that dies at 60% must not start over.
5. Emit the identity-coverage report from Part 2.

Idempotent throughout, keyed on the Razorpay payment id, so re-running cannot duplicate an order.

### Phase 3 · Turn on live sync

Register the webhook. `payment.captured` arrives → verify signature → upsert customer → insert order. This code path already exists and is already idempotent; it is the same handler `/api/simulate/payment` exercises in the demo.

From here their data stays current with no polling.

### Phase 4 · Start collecting feedback

The merchant has **zero reviews** on day one. The review-language detector, theme trends and time-of-day analysis are all dead until a few hundred exist.

- Add a feedback link to the payment success page — Razorpay payment links accept a `callback_url`, and hosted checkout has a success redirect.
- The link carries a signed token identifying the payment, so **every review is joined to a customer and an order by construction**. That join is the whole reason this data is more valuable than public reviews.
- New reviews are labelled by the extraction pass — which by now is a **queue worker**, not a synchronous batch.

Meanwhile the **behavioural detector works from day one**, because it needs only payment history. That split was deliberate.

### Phase 5 · Calibrate to *this* merchant *(the step most people would skip)*

**Every threshold in the demo is a constant tuned to synthetic data:**

```python
LAPSED_MIN_LTV_INR    = 5000      # meaningless if their AOV is ₹80, or ₹8,000
LAPSED_MIN_ORDERS     = 5
LAPSED_MIN_SILENT_DAYS = 60
CHURN_MIN_LTV_INR     = 15000
```

For a real merchant these become **percentiles of their own distribution**, computed during a calibration window and stored per merchant:

- "high value" → top quartile of lifetime spend, not ₹15,000
- "established rhythm" → enough orders to have a stable median gap, checked per customer
- "silent" → still `3× their own median gap`, which is the one rule that already generalises, because it was relative from the start

Demand planning needs a similar warm-up: `MIN_OBSERVATIONS = 6` comparable windows before it claims a pattern, so roughly six weeks before a weekly peak is trustworthy.

### Phase 6 · Shadow mode — the agent runs, but spends nothing

**Two to four weeks. No money moves.** The agent scans, raises opportunities, shows evidence and money figures — and every one is a proposal the owner reads and rates. Nothing is sent.

This answers the only question that matters before spending: **are these the right customers?** The owner knows their regulars. If the agent flags someone who moved cities, that is a false positive I need to see *before* it costs anything.

Exit criteria I would want: the owner agrees with the majority of proposals, and no proposal is obviously wrong.

### Phase 7 · Go live with real money — small

- **Live Razorpay keys**, and start with caps far below what they authorised. A ₹500 daily budget, not ₹5,000.
- **Holdout from the very first campaign**, so incrementality is measurable from day one rather than retrofitted.
- **Watch the audit log daily** for the first fortnight. Every refusal is a bound working; every failure is a bug.
- Raise the caps only when the numbers justify it.

### Phase 8 · Measure whether it actually made money

Attribution is exact from day one — a payment through a campaign link maps to that campaign by construction. **Incrementality takes months**, because one merchant's sample size is small. Until then every lift figure stays labelled directional, with both group sizes shown.

The number I would report honestly: *revenue attributed, incentive actually spent, and the treated-vs-control return rates with their sample sizes.* Not a single flattering figure.

---

## Part 4 — What has to be built that does not exist today

| Needs building | Why | Rough effort |
|---|---|---|
| Authentication | There is none | 2–3 days |
| `merchant_id` everywhere + row-level security | Only 2 of 13 tables have it | 3–4 days |
| Postgres migration + Alembic | Concurrency and real migrations | 1 day |
| Credential vault | Live keys must never sit in the app DB | 1–2 days |
| Resumable backfill job | Tens of thousands of API calls | 3–4 days |
| Per-merchant policy config | Bounds are module constants today | 2 days |
| Per-merchant threshold calibration | Constants are tuned to synthetic data | 3–4 days |
| Queue worker for extraction | Synchronous batch today | 2 days |
| Feedback capture on the payment page | Reviews start at zero | 2–3 days |
| Consent capture, opt-out, DLT registration | Legally required before any message | 1–2 weeks incl. approvals |
| Distributed aggregate cache | `aggregates.py` is per-process | 2 days |

**Roughly six to eight weeks of engineering** before one real merchant could be safely live — and most of it is *not* the AI. The agent, the policy engine, the audit trail and the money loop are the parts that already work.

---

## Part 5 — The short answer

> *"First I would measure, not build. Pull six months of their Razorpay payments and report what fraction carry a customer identity — because everything here depends on knowing which customer a payment belongs to, and in a restaurant much of the money arrives as anonymous UPI. That number tells them honestly how much of their business this can see.*
>
> *Then: OAuth into their Razorpay account so I never hold their secret key; a resumable backfill of their payment history; a webhook for live sync — that handler already exists and is already idempotent; and a feedback link on the payment success page so reviews start accumulating joined to real orders.*
>
> *Before any of that, though, three things have to be built that the demo does not have: authentication, a merchant id on every table with row-level security, and Postgres. And the thresholds in my detectors are constants tuned to synthetic data — for a real merchant they become percentiles of their own distribution.*
>
> *Then two to four weeks of shadow mode where the agent proposes and nothing sends, because the only question worth answering before spending money is whether these are the right customers. Then live keys with caps far below what they authorised, and a holdout from the first campaign.*
>
> *Six to eight weeks, and most of it is not the AI — the agent, the policy engine and the audit trail are the parts that already work."*
