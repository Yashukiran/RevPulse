# What is wrong with RevPulse

Every system has limits. A system that moves money should be able to state its own, precisely, before anyone else does. This document is that statement.

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

**Aggregates** are computed on demand in Python over full table scans. That is fine for hundreds of customers and untenable for hundreds of merchants; they become materialised, incrementally-updated views.

**SQLite** is a deliberate choice for reproducibility — a judge clones the repo and runs it with no database to provision. It is not a production choice. The schema is the design; the engine is not.

**The agent layer scales as it stands.** It reasons over aggregates rather than raw text, so its token cost is independent of review volume. That was a design decision, not luck.

**Not yet built:** multi-merchant tenancy and isolation, background job scheduling, per-merchant policy configuration, and any authentication beyond a demo login.
