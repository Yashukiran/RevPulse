# AI judgment, failure recovery, and what is still wrong

Three things a system that moves money should be able to say about itself: where it deliberately refused to use a model, what broke while building it, and what remains wrong. This document is that statement.

- **[Part 1 — Where the model is, and where it deliberately is not](#part-1--where-the-model-is-and-where-it-deliberately-is-not)**
- **[Part 2 — What broke, and what I did about it](#part-2--what-broke-and-what-i-did-about-it)**
- **[Part 3 — What is still wrong with RevPulse](#part-3--what-is-still-wrong-with-revpulse)**

---

# Part 1 — Where the model is, and where it deliberately is not

The rule the whole system turns on: **the model can ask for anything, and can execute nothing.** Between the asking and the doing sits deterministic Python.

## Where a model is NOT used, and why

### 1 · All money arithmetic — `opportunities.py`

Every rupee figure is computed in Python from the merchant's own transactions. `compute_money()` produces four figures — lifetime value at risk, realistically recoverable, expected recovered, maximum exposure — by summing and multiplying real order amounts.

**Why not the model:** a language model that can invent a rupee figure is a liability inside a payments product. Not "usually accurate" — *incapable of being wrong*, because it never touches the sum. The model receives the finished numbers and is told to use only those.

### 2 · The policy engine — `policy.py`

180 lines of pure functions returning `ALLOWED`, `NEEDS_APPROVAL` or `BLOCKED`, plus the exact rule that fired. No model call anywhere in the file. Same inputs, same verdict, every time.

**Why not the model:** *"the model usually refuses"* is not a safety guarantee. A bound that holds 99% of the time is a bound that fails on the hundredth campaign. Every limit here is an integer compared against another integer.

### 3 · Churn detection — `opportunities.py`

Both detectors are explicit rules over transaction data. `detect_lapsed_high_value()` qualifies a customer on lifetime spend, order count, absolute days silent, and silence exceeding **3× their own median gap between orders**. No model, and it needs no reviews at all.

**Why not the model:** the merchant is being asked to spend money on this. The evidence shown to them has to *be* the basis of the decision, not a plausible story told about it. A rule can be printed on the card — and it is, in monospace, on the evidence panel.

### 4 · Demand forecasting — `demand.py`

The forecast is the median of the last 8 comparable windows. Accuracy is measured by walk-forward backtest: re-forecast past windows using only prior data.

**Why not the model:** an owner can check a median. *"13 of the last 14 Fridays ran busier"* is the actual arithmetic, so the evidence on screen is the reason for the number. A model's forecast would need to be trusted; this one can be verified.

### 5 · Attribution — `routers/actions_api.py`

When a payment arrives, a new `Order` row is written carrying the `campaign_id`. Revenue attributed to a campaign is therefore a one-column database filter.

**Why not the model:** attribution by construction cannot be argued with. Anything statistical or inferred can.

### 6 · The holdout split — `actions.py`

Seeded off the campaign id, so the same campaign always splits the same way.

**Why not the model, and why not even plain randomness:** a re-rollable split is one you can quietly re-roll until the numbers look better. Seeding makes that impossible, and that sentence is in the code as a comment.

## Where a model IS used — four places, all bounded

| Where | Model | What it does | What happens if it fails |
|---|---|---|---|
| `agent/extraction.py` | Haiku | Labels each review with sentiment, themes from a **fixed vocabulary of 11**, urgency, churn signal. One batched pass, cached in DB columns forever | The review is saved unlabelled rather than lost |
| `opportunities.py` `_explain()` | Haiku | Turns finished figures into two sentences for the merchant. Told to use only the numbers given | A deterministic sentence takes its place; the card is fully usable |
| `demand.py` `_recommendation()` | Haiku | Same pattern, on the forecast | Same deterministic fallback |
| `agent/loop.py` | Sonnet | The interactive agent: chooses which tools to call, reacts to policy verdicts | Turn limit, and tool errors return as data rather than crashing |

Note what every row has in common: **the model's output is language, never a number, and never an action.** And every one degrades to a working product without it.

## Two supporting decisions worth naming

**The theme vocabulary is closed, not free-form.** Eleven allowed themes. Let a model invent labels and "slow delivery", "late", "took forever" and "delivery delay" become four separate themes — the trend chart becomes meaningless. The honest cost: a genuinely new problem has nowhere to go but `other`. At scale the answer is embedding-based clustering.

**The agent reasons over aggregates, never raw text at scale.** `get_review_stats()` returns counts, not reviews. So the agent's token cost is **independent of review volume** — at a million reviews the extraction becomes a streaming job and the agent layer does not change.

---

# Part 2 — What broke, and what I did about it

Every failure below is real. Most are documented in a code comment or the commit that fixed them, so they can be checked rather than taken on trust.

## 1 · The agent did all the work, then answered with nothing

**Symptom.** The loop ran, tools executed and returned data, then the final message came back completely blank. No error, no exception — an empty string where the answer should be.

**Cause.** I did not add a retry. I logged `stop_reason` and found `max_tokens`: extended thinking was consuming the entire output budget before a single visible token was produced. The model was thinking itself into silence.

**Fix.** Disabled thinking on the loop and raised the ceiling — `thinking={"type": "disabled"}`, `max_tokens=4000` in `agent/loop.py`. Commit `c715fe0`.

**Lesson.** Read the actual stop reason instead of guessing. Every LLM API tells you why it stopped; almost nobody looks. An empty response is not a mystery, it is a field you did not read.

## 2 · A policy refusal would have killed the whole run

**Symptom.** The obvious implementation of `BLOCKED` is to raise an exception — which kills the agent mid-conversation the first time it asks for something over budget, and shows the merchant a crash instead of an explanation.

**Cause.** A design mistake, not a runtime one: treating a *rule* as an *error*. A refusal is an expected outcome of a bounded system, not a failure of it.

**Fix.** The verdict is returned to the model as ordinary tool-result data, so it can reason about it. The model receives `daily-budget: ₹3,800 spent + ₹2,000 requested > ₹5,000/day` and routes around it compliantly — explaining the refusal in plain language and submitting a smaller version.

**Lesson.** In an agent, the line between an error and a fact is a design decision. Anything you `raise`, the model cannot see. Anything you `return`, it can reason about. `scripts/demo_failure.py` proves this reproducibly — and *asserts* the recovery came in under the remaining budget, so it is a tested claim rather than a lucky run.

## 3 · A safety rule made the system unrecoverable

**Symptom.** Mid-campaign, Razorpay rate-limited on customer 8 of 10. The whole campaign aborted. On retry, **my own frequency cap blocked it** — because the seven customers already reached had been recorded as "offered".

**Cause.** Two individually correct pieces of code interacting badly. Failure was handled *per batch*, but state was written *per customer*, so a partial failure left partial state that the safety rule read as a completed campaign.

**Fix.** Moved failure handling from per-batch to per-customer in `actions.py`. The batch continues, each failure is recorded against the customer it belongs to, and budget reserves against customers **actually reached** rather than intended. A campaign fails outright only if not one link could be created. A 0.25s stagger between calls avoids tripping the burst limit in the first place. Commit `12a396d`.

**Lesson.** Partial failure is the normal case in distributed systems, and my guardrail had no concept of it. This is the bug I would lead with: not a typo or a misread doc, but a fault in the *interaction* between two correct components — which is what production failure actually looks like. A safety rule can itself be the outage.

## 4 · My own tests reported two unauthorised money actions

**Symptom.** After seeding demo data, the policy suite dropped to **12/15** and the evaluation harness reported **2 unauthorised money actions** — the most alarming output a payments safety test can produce.

**Cause.** The engine was correct; the *tests* were wrong. They hard-coded customer ids, and policy verdicts are state-dependent by design — a customer who had since been offered something was now *correctly* blocked, while the test still expected allowed.

**Fix.** `scripts/policy_fixtures.py`. Every test builds its own throwaway customers in exactly known states and snapshots then restores the day's budget ledger, so they score identically on a fresh clone or mid-demo. Commit `1d6c643`.

**Lesson.** A test that changes its answer based on demo data is worse than no test — it burns your trust in the thing it is meant to protect. The skill that mattered was separating *"my code is broken"* from *"my measurement is broken"* under pressure, on the scariest possible signal.

## 5 · A headline number that would not have survived one question

**Symptom.** The opportunity card led with **"Revenue at risk: ₹79,090"** next to a ₹409 offer. That reads as a 200× return. It is not — ₹79,090 is those customers' historical lifetime spend. Money already banked.

**Cause.** Collapsing four different quantities into one impressive figure, because the impressive figure was easy to compute and looked good.

**Fix.** Split into four, each honestly labelled on screen: lifetime value at risk *("already earned — context, not recoverable")*, realistically recoverable, expected (a projection with its assumption printed beside it), and maximum exposure (exact). Commit `79c9eb4`.

**Lesson.** I lost the big number and gained a defensible one. Any payments person would have taken the original apart in seconds, and once one figure collapses nobody believes the rest.

## 6 · Razorpay test mode ran out of payment links — permanently

**Symptom.** Campaign creation started failing. Razorpay test mode allows **30 payment links per account for the lifetime of the account**, and cancelling does not free the quota.

**Cause.** Not a bug in my code — a sandbox ceiling I had not read about, hit by re-running demo scripts during development.

**Fix.** Three things. An automatic fallback to the Razorpay **Orders API** (unlimited, and the object a real in-app checkout is built on), with attribution unchanged because the offer code travels in the same `notes` field. Backoff retry at 1s, 3s, 8s, 20s for rate limits and dropped connections. And `evaluate.py` now stubs the provider by default so the harness stays re-runnable, with the live proof in `test_money_chain.py`.

**Lesson.** Read the sandbox's limits before building a demo that depends on them, and never let a quota be the thing that stops someone reproducing your results.

## 7 · Seventeen seconds to summarise 789 reviews

**Symptom.** Switching tabs on the deployed dashboard took up to seven seconds. `/api/stats` alone took **17.2s** — for only 789 reviews, so it could not be the data volume.

**Cause.** A classic **N+1 query**. The stats function touched `r.customer` per review to read one zone string, and each touch lazy-loaded a row: 789 separate round trips. Alongside it, the transaction view hydrated 43,909 ORM objects to sum three columns, and the forecast scanned the order table three times.

**Fix.** Resolve zones from one query; read plain column tuples instead of ORM objects; and derive all order totals **once** into `aggregates.py`, reused until the table changes (guarded by a `MAX(id)` lookup, deliberately not `COUNT(*)`, which scans).

| Endpoint | Before | After |
|---|---|---|
| `/api/stats` | 17.2s | **0.44s** |
| `/api/transactions?compare_theme` | 21.8s | **0.50s** |
| `/api/demand/forecast` | 21.9s | **3.0s** |

**Lesson.** An ORM will hide a thousand queries behind one attribute access. The tell was that the slowness did not scale with the data. I also verified the optimisation changed nothing: the payloads serialise **byte-identical** against the pre-optimisation commit, and the harness still reports 5/5, 0/2, 3/3, 100/100.

## 8 · A deploy that reported success while being entirely broken

**Symptom.** Both services deployed green. The dashboard loaded, styled and titled correctly. **Every screen said "Failed to load: Failed to fetch."**

**Cause.** The host's `fromService … property: host` returns the *service name*, not the hostname, so the bundle called `https://revpulse-api` — a host that does not resolve. The browser console gave it away: `wss://revpulse-api/ws/audit failed`.

**Fix.** Set the URL explicitly, then made the class of mistake impossible: `vite.config.js` now **fails the build** if the API URL is ever a bare host again.

**Lesson.** "It built successfully" and "it works" are different claims, and only one of them was tested. A broken site that looks deployed is worse than a build that stops — so I made the build stop.

## Smaller ones, for completeness

| What broke | Cause | Fix |
|---|---|---|
| An item read **"1 → 3, +79%"** | Percentage computed from unrounded values, so it did not match the numbers beside it | Round to whole units *before* computing the change. An owner doing mental arithmetic would have caught it, then distrusted every other number |
| Everything showed as **"5h ago"** | Timestamps stored as naive UTC; the browser read them as local time | `utc_iso()` appends the `Z`. One character between a live-looking demo and a broken one |
| Both servers **kept dying** | Started as background jobs owned by a parent session; when it cycled, the OS reaped the process group | `start.bat` launches them as independent windows, with `--strictPort` so Vite cannot drift to 5174 |
| `pkg_resources` **import crash** | The Razorpay SDK imports a module removed in setuptools 81+ | Pinned `setuptools<81` **with the reason in a comment**, so nobody helpfully unpins it |

## The git history is the failure log

Every commit subject below is a bug found and fixed. The repository can be read as the project being debugged, not just built.

```
c715fe0  disable thinking in tool loop, upgrade anthropic sdk
1d6c643  make test harnesses hermetic
86806d2  make the opportunity scan explain itself when it finds nothing
79c9eb4  separate lifetime value from recoverable revenue on opportunity cards
12a396d  keep a campaign alive when one customer's payment link fails
99e4f0c  point the dashboard at a hostname browsers can actually resolve
07b5a32  stop reading the same rows over and over
5731aad  derive the order totals once instead of on every request
```

---

# Part 3 — What is still wrong with RevPulse

Every system has limits. A system that moves money should be able to state its own, precisely, before anyone else does.

## 1. Attribution is exact. Causation is not.

When a customer pays through a campaign link, that payment maps to one opportunity by construction — a unique Razorpay object and offer code per customer, not a statistical model. That part is airtight.

It proves nothing about whether the offer *caused* the return. Some of those customers would have ordered again anyway; for them the discount was margin given away for no reason. This is cannibalisation, and it is the way this product most plausibly loses a merchant money.

**What the holdout does.** Segments of six or more hold roughly 30% back: same profile, no offer, no link. Return rates are compared across both groups over the same 30-day window, counting *any* order rather than only ones through our links — a control customer has none, and a treated customer who returns by another route still returned. The split is seeded off the campaign id, so it cannot be quietly re-rolled until the numbers improve.

**What the holdout does not do.** One merchant running a ten-customer campaign produces samples far too small for statistical significance. Every lift figure is labelled directional and shown with both group sizes. It is a mechanism for measuring incrementality, not a claim to have measured it. Reaching significance needs many campaigns across many merchants; that is a property of scale, not of the code.

Below six customers the holdout is skipped and the reason recorded. A control group of two proves nothing, and reporting nothing is more honest than reporting a number that resembles evidence.

## 2. Cold start: a new merchant gets little on day one

The product needs history to say anything. A merchant who signs up today has no first-party feedback at all and possibly thin transaction history.

**Works immediately** (from whatever payment history exists): lapsed high-value detection, lifetime value and average order value, revenue trends, top items. The behavioural detector was built precisely because it does not wait for anyone to write a review.

**Needs weeks:** the review pipeline. Feedback is collected at the payment moment, so volume accumulates at the rate the merchant takes payments. Theme trends, time-of-day and zone concentration, and the churn-language detector are all meaningless until a few hundred reviews exist.

A merchant with neither payment history nor feedback gets nothing useful, and should be told that rather than sold a dashboard of empty charts.

## 3. Restaurants are the demo, not the best vertical

The demo merchant is a Bengaluru restaurant because it is instantly relatable. It is not where this product works best, and pretending otherwise would be dishonest.

Everything here depends on **customer identity being attached to a payment**. In Indian restaurants that link is weak: much of the money arrives as UPI QR scans or cash with no email or phone captured, and delivery aggregators own the customer relationship and do not share it. A restaurant may process substantial volume while remaining largely anonymous to us.

The architecture is vertical-agnostic. It fits businesses where every transaction carries an identity by default — D2C brands, subscription services, clinics, online education, service businesses that invoice. Those merchants have exactly the data this product reasons over.

This is a positioning judgement, not an apology: the loop is identical everywhere; only the density of identified transactions changes.

## 4. A discount is sometimes the wrong intervention

The system has one lever: money off the next order. That lever suits a loyal customer who had one bad night. It does not suit a customer who has been failed three times — offering that person 15% off is offering to sell them the same problem slightly cheaper, and it can read as insulting.

Two things follow. First, targeting matters more than generosity: the detectors deliberately exclude low-value and one-time customers, because untargeted win-back campaigns lose money on people who were never leaving. Second, the customer-protection bounds exist to stop a struggling merchant carpet-bombing unhappy customers — one offer per customer per 30 days, no re-targeting anyone who already redeemed — both enforced by the policy engine rather than by good intentions.

What genuinely recovers a burned customer is a reply that owns the failure and an operational fix. The product supports the first and surfaces the evidence for the second. The offer is a tourniquet, not a cure.

## 5. Messaging compliance is acknowledged, not implemented

Sending promotional messages to customers in India is regulated: consent is required, opt-out must be honoured, and promotional SMS requires DLT registration of sender and template. Data handling falls under the DPDP Act.

None of this is built. In the demo, notification is switched off entirely — `notify: {sms: false, email: false}` — because the seeded customers have invented phone numbers and sending real messages to invented numbers would be wrong. In production Razorpay delivers payment links itself, which moves part of this burden to a regulated party, but consent capture, opt-out handling and template registration would all have to exist before a single real message went out.

## 6. What is real and what is simulated

**Real:** the Razorpay integration (objects created on a live test-mode account, carrying campaign metadata), the policy engine and every verdict it returns, the write-ahead audit trail, idempotency keys and their retry behaviour, the review extraction pipeline, and all money arithmetic.

**Simulated:** customer payments. Nobody has entered a card. Payments are triggered through `/api/simulate/payment`, which runs the *same handler* the real webhook calls — the code path being demonstrated is the production one; only the trigger differs. Campaign response rates in the evaluation report are seeded probabilities, labelled `[SIMULATED]` at every appearance.

**Synthetic:** the dataset. 789 reviews, 1,204 customers and 43,909 orders generated by two committed, seeded scripts — `generate_data.py` plants the patterns and the answer key, and `add_order_volume.py` adds the review-less walk-in volume that gives demand forecasting something to work with — including decoys that must *not* be flagged, so false positives are measurable rather than merely absent. No real merchant has used this system.

The 30% redemption rate used in projections is an assumption, printed beside the figure it produces, because there is no completed campaign history to forecast from.

## 7. What breaks at scale

**Review extraction** runs as a batched job (twenty reviews per model call) writing into SQLite. At a million reviews this is wrong in three ways: the pass is synchronous, the storage is a single file, and the theme vocabulary is fixed. The intended answers are streaming ingestion, lakehouse storage with proper partitioning, and embedding-based clustering with periodic re-labelling instead of a hand-written list.

**Aggregates** are derived once and held in memory (`aggregates.py`), invalidated when the order table changes. That is the right shape but the wrong mechanism at scale: the cache is per-process, so every worker rebuilds it, and it holds the whole business in RAM. These become materialised, incrementally-updated views in the database.

**SQLite** is a deliberate choice for reproducibility — a judge clones the repo and runs it with no database to provision. It is not a production choice. The schema is the design; the engine is not.

**The agent layer scales as it stands.** It reasons over aggregates rather than raw text, so its token cost is independent of review volume. That was a design decision, not luck.

**Not yet built:** multi-merchant tenancy and isolation, background job scheduling, per-merchant policy configuration, and **any authentication at all** — the dashboard is currently open.
