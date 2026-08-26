"""The proactive layer: the agent finds revenue opportunities on its own.

Design rule, and the one to defend in an interview: **every number here is
computed in Python from the merchant's data; the model only writes the
explanation.** A language model that invents a rupee figure is a liability, so
it never touches the maths — it reads the evidence we assembled and says why it
matters in plain language.

Each scan produces Opportunity rows carrying:
  - the evidence (the actual reviews and transactions behind the signal)
  - revenue at risk (hard number: LTV of the affected customers)
  - expected recovered revenue (a projection, with its assumption stated)
  - maximum financial exposure (worst case: every customer redeems)
  - the concrete action proposed, already run through the policy engine

Scenario implemented: churn-risk detection -> win-back offer.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from sqlalchemy import func

from . import audit, policy
from .db import utc_iso
from .models import Customer, OfferRedemption, Opportunity, Order, Review

# ---- detection thresholds (deterministic, documented, defensible) ----
# ₹15,000 lifetime spend is the merchant's "high value" line — the same
# threshold the evaluation harness scores against, so detection is measurable.
CHURN_MIN_LTV_INR = 15000
CHURN_LOOKBACK_DAYS = 120       # how recent the churn signal must be
WINBACK_DISCOUNT_PCT = 15       # within the 20% policy cap
WINBACK_EXPIRY_DAYS = 7
MAX_SEGMENT = 10                # one proposal stays reviewable by a human

# ---- lapsed-customer detection (transactions only, no reviews, no model) ----
# Reviews exist for a small minority of customers; transaction behaviour exists
# for all of them. Behaviour is therefore the PRIMARY churn signal and reviews
# are the enrichment layer that explains WHY someone is leaving.
# Deliberately lower than the churn threshold, and the reason matters: a
# churn-signal customer is still active and merely says they may leave, so we
# hold a higher bar before spending on someone who might not have gone anywhere.
# A lapsed customer has already stopped — the loss is realised, not hypothetical
# — so an established regular is worth recovering at a lower lifetime value.
LAPSED_MIN_LTV_INR = 5000
LAPSED_MIN_ORDERS = 5           # enough history to have an established rhythm
LAPSED_MIN_SILENT_DAYS = 60     # absolute floor, regardless of cadence
LAPSED_CADENCE_MULTIPLE = 3.0   # silent for 3x their own normal gap

# Projection assumption. We have no historical campaign data for this merchant,
# so this is an explicitly stated assumption, never presented as a forecast.
ASSUMED_REDEMPTION_RATE = 0.30
ASSUMPTION_NOTE = (
    f"Projection assumes a {int(ASSUMED_REDEMPTION_RATE * 100)}% redemption rate. "
    "This merchant has no completed win-back campaigns yet, so that figure is an "
    "assumption, not a forecast from their own history. Maximum exposure below is "
    "exact: it is what the offer costs if every targeted customer redeems."
)

EXPLAIN_MODEL = "claude-haiku-4-5-20251001"


def _blocked_customer_ids(db) -> set[int]:
    """Customers the guardrails would refuse: recently offered, or already redeemed."""
    cutoff = datetime.utcnow() - timedelta(days=policy.OFFER_FREQUENCY_DAYS)
    recent = {r.customer_id for r in db.query(OfferRedemption)
              .filter(OfferRedemption.sent_ts >= cutoff)}
    redeemed = {r.customer_id for r in db.query(OfferRedemption)
                .filter(OfferRedemption.redeemed_ts.isnot(None))}
    return recent | redeemed


def _open_opportunity_customers(db) -> set[int]:
    """Customers already covered by an opportunity awaiting a decision."""
    ids: set[int] = set()
    for o in db.query(Opportunity).filter(
        Opportunity.status.in_(["open", "awaiting_approval", "approved"])
    ):
        ids.update(json.loads(o.customer_ids_json))
    return ids


def compute_money(targets: list[dict]) -> dict:
    """The money maths for a win-back proposal. Deterministic, from the
    merchant's own transactions — the model never produces any of these.

    Four figures, deliberately distinguished:
      revenue_at_risk_inr    lifetime value already earned from these customers.
                             CONTEXT for how much the relationship is worth. It
                             is not money this offer can recover.
      recoverable_revenue_inr what ONE returning order from each is worth at the
                             discounted price — the honest upper bound of what
                             this specific intervention can bring back.
      expected_revenue_inr   a projection: recoverable x an assumed redemption
                             rate, always shown with the assumption stated.
      max_exposure_inr       exact worst case: the incentive given away if every
                             targeted customer redeems.
    """
    discounted = [int(round(t["aov_inr"] * (1 - WINBACK_DISCOUNT_PCT / 100))) for t in targets]
    incentive = [t["aov_inr"] - d for t, d in zip(targets, discounted)]
    recoverable = sum(discounted)
    return {
        "revenue_at_risk_inr": sum(t["ltv_inr"] for t in targets),
        "recoverable_revenue_inr": recoverable,
        "expected_revenue_inr": int(round(recoverable * ASSUMED_REDEMPTION_RATE)),
        "max_exposure_inr": sum(incentive),
    }


def detect_churn_risk(db, ignore_open: bool = False,
                      stats: dict | None = None) -> dict | None:
    """Find high-value customers whose own words say they are leaving.

    Signal = a churn-flagged review from a customer whose lifetime spend is
    above the threshold. Returns a candidate dict, or None if nothing qualifies.

    In normal operation customers already covered by an undecided opportunity
    are skipped, so the merchant is never shown the same proposal twice. The
    evaluation harness passes ignore_open=True to measure raw detection.
    """
    cutoff = datetime.utcnow() - timedelta(days=CHURN_LOOKBACK_DAYS)
    ltv = dict(db.query(Order.customer_id, func.sum(Order.amount_inr))
               .group_by(Order.customer_id).all())
    aov = dict(db.query(Order.customer_id, func.avg(Order.amount_inr))
               .group_by(Order.customer_id).all())
    last_order = dict(db.query(Order.customer_id, func.max(Order.ts))
                      .group_by(Order.customer_id).all())

    churn_reviews = (db.query(Review)
                     .filter(Review.churn_signal.is_(True), Review.ts >= cutoff)
                     .order_by(Review.ts.desc()).all())

    blocked = _blocked_customer_ids(db)
    already_covered = set() if ignore_open else _open_opportunity_customers(db)

    candidates: list[dict] = []
    seen: set[int] = set()
    excluded_by_policy = 0
    excluded_covered = 0
    high_value_matches = 0
    for r in churn_reviews:
        cid = r.customer_id
        if cid in seen:
            continue
        if int(ltv.get(cid, 0)) < CHURN_MIN_LTV_INR:
            continue
        seen.add(cid)
        high_value_matches += 1
        if cid in already_covered:
            excluded_covered += 1
            continue
        if cid in blocked:
            excluded_by_policy += 1
            continue
        cust = db.get(Customer, cid)
        if not cust:
            continue
        candidates.append({
            "customer_id": cid,
            "name": cust.name,
            "zone": cust.zone,
            "ltv_inr": int(ltv.get(cid, 0)),
            "aov_inr": int(aov.get(cid, 0) or 0),
            "last_order": last_order[cid].isoformat() if cid in last_order else None,
            "review": {"id": r.id, "ts": r.ts.isoformat(), "rating": r.rating,
                       "text": r.text, "themes": json.loads(r.themes_json or "[]")},
        })

    if stats is not None:
        stats.update({
            "churn_reviews_in_window": len(churn_reviews),
            "high_value_matches": high_value_matches,
            "excluded_recent_offer": excluded_by_policy,
            "excluded_already_proposed": excluded_covered,
            "min_ltv_inr": CHURN_MIN_LTV_INR,
            "lookback_days": CHURN_LOOKBACK_DAYS,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda c: -c["ltv_inr"])
    targets = candidates[:MAX_SEGMENT]

    money = compute_money(targets)

    return {
        "kind": "churn_risk_winback",
        "targets": targets,
        "revenue_at_risk_inr": money["revenue_at_risk_inr"],
        "recoverable_revenue_inr": money["recoverable_revenue_inr"],
        "expected_revenue_inr": money["expected_revenue_inr"],
        "max_exposure_inr": money["max_exposure_inr"],
        "excluded_by_policy": excluded_by_policy,
        "proposed_tool": "create_recovery_offer",
        "proposed_args": {
            "customer_ids": [c["customer_id"] for c in targets],
            "discount_pct": WINBACK_DISCOUNT_PCT,
            "expiry_days": WINBACK_EXPIRY_DAYS,
            "reason": "High-value customers whose recent reviews signal churn",
        },
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def detect_lapsed_high_value(db, ignore_open: bool = False,
                             stats: dict | None = None) -> dict | None:
    """Find valuable regulars who have quietly stopped ordering.

    Purely behavioural: no review required, no model involved. A customer is
    lapsed when they have real history (spend and order count above the line),
    an established ordering rhythm, and have now been silent for far longer than
    that rhythm — measured against their own past behaviour, not a global rule,
    because a weekly customer going quiet for a month means something a
    quarterly customer going quiet for a month does not.

    This is the detector that does not depend on anyone writing a review.
    """
    ref_now = datetime.utcnow()
    orders_by_customer: dict[int, list] = {}
    for o in db.query(Order).order_by(Order.ts).all():
        orders_by_customer.setdefault(o.customer_id, []).append(o)

    blocked = _blocked_customer_ids(db)
    already_covered = set() if ignore_open else _open_opportunity_customers(db)

    candidates: list[dict] = []
    behaviour_matches = 0
    excluded_by_policy = 0
    excluded_covered = 0

    for cid, orders in orders_by_customer.items():
        if len(orders) < LAPSED_MIN_ORDERS:
            continue
        ltv = sum(o.amount_inr for o in orders)
        if ltv < LAPSED_MIN_LTV_INR:
            continue

        gaps = [(orders[i].ts - orders[i - 1].ts).days for i in range(1, len(orders))]
        cadence = _median([g for g in gaps if g >= 0]) or 0.0
        silent_days = (ref_now - orders[-1].ts).days
        if silent_days < LAPSED_MIN_SILENT_DAYS:
            continue
        if cadence and silent_days < cadence * LAPSED_CADENCE_MULTIPLE:
            continue

        behaviour_matches += 1
        if cid in already_covered:
            excluded_covered += 1
            continue
        if cid in blocked:
            excluded_by_policy += 1
            continue
        cust = db.get(Customer, cid)
        if not cust:
            continue
        candidates.append({
            "customer_id": cid,
            "name": cust.name,
            "zone": cust.zone,
            "ltv_inr": int(ltv),
            "aov_inr": int(round(ltv / len(orders))),
            "last_order": orders[-1].ts.isoformat(),
            "order_history": {
                "orders": len(orders),
                "median_gap_days": int(round(cadence)),
                "silent_days": silent_days,
                "silent_multiple": round(silent_days / cadence, 1) if cadence else None,
                "first_order": orders[0].ts.isoformat(),
            },
        })

    if stats is not None:
        stats.update({
            "lapsed_behaviour_matches": behaviour_matches,
            "lapsed_excluded_recent_offer": excluded_by_policy,
            "lapsed_excluded_already_proposed": excluded_covered,
            "lapsed_min_ltv_inr": LAPSED_MIN_LTV_INR,
            "lapsed_min_silent_days": LAPSED_MIN_SILENT_DAYS,
        })

    if not candidates:
        return None

    candidates.sort(key=lambda c: -c["ltv_inr"])
    targets = candidates[:MAX_SEGMENT]
    money = compute_money(targets)

    return {
        "kind": "lapsed_high_value",
        "targets": targets,
        "revenue_at_risk_inr": money["revenue_at_risk_inr"],
        "recoverable_revenue_inr": money["recoverable_revenue_inr"],
        "expected_revenue_inr": money["expected_revenue_inr"],
        "max_exposure_inr": money["max_exposure_inr"],
        "excluded_by_policy": excluded_by_policy,
        "proposed_tool": "create_recovery_offer",
        "proposed_args": {
            "customer_ids": [c["customer_id"] for c in targets],
            "discount_pct": WINBACK_DISCOUNT_PCT,
            "expiry_days": WINBACK_EXPIRY_DAYS,
            "reason": "High-value regulars who have stopped ordering",
        },
    }


def _explain(candidate: dict) -> str:
    """One short model call: turn the evidence into a merchant-readable rationale.

    The model receives only figures we computed and may not introduce new ones.
    If the call fails we fall back to a deterministic sentence — the opportunity
    is still fully usable without the model.
    """
    targets = candidate["targets"]
    lapsed = candidate["kind"] == "lapsed_high_value"
    signal = ("have stopped ordering after months of regular business"
              if lapsed else "left churn-signal reviews recently")
    fallback = (
        f"{len(targets)} high-value customers {signal}. "
        f"Together they have spent ₹{candidate['revenue_at_risk_inr']:,} with this "
        f"merchant. A {WINBACK_DISCOUNT_PCT}% win-back offer costs at most "
        f"₹{candidate['max_exposure_inr']:,} and targets exactly the customers whose "
        f"repeat business is most valuable to protect."
    )
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        def _fact(t: dict) -> dict:
            base = {"name": t["name"], "ltv_inr": t["ltv_inr"], "aov_inr": t["aov_inr"],
                    "last_order": t["last_order"]}
            if "review" in t:
                base["review"] = t["review"]["text"][:240]
                base["rating"] = t["review"]["rating"]
            if "order_history" in t:
                base["order_history"] = t["order_history"]
            return base

        facts = {
            "customers": [_fact(t) for t in targets[:6]],
            "count": len(targets),
            "revenue_at_risk_inr": candidate["revenue_at_risk_inr"],
            "max_exposure_inr": candidate["max_exposure_inr"],
            "expected_revenue_inr": candidate["expected_revenue_inr"],
            "discount_pct": WINBACK_DISCOUNT_PCT,
        }
        msg = client.messages.create(
            model=EXPLAIN_MODEL,
            max_tokens=320,
            messages=[{"role": "user", "content": (
                "You are the growth agent for Biryani House, a Bengaluru delivery "
                "restaurant. Below is a revenue opportunity you detected, with figures "
                "already computed from the merchant's transaction data.\n\n"
                f"{json.dumps(facts, indent=2)}\n\n"
                + ("Write 2-3 sentences for the merchant explaining what you found, "
                   "naming one customer and how long they have been silent relative to "
                   "their normal ordering rhythm, and why acting now protects revenue. "
                   if lapsed else
                   "Write 2-3 sentences for the merchant explaining what you found, "
                   "quoting one customer's words as evidence, and why acting now "
                   "protects revenue. ")
                + "Use ONLY the figures given — never invent a number. Plain language, no "
                  "headings, no bullet points."
            )}],
        )
        text = msg.content[0].text.strip()
        return text or fallback
    except Exception:
        return fallback


def explain_no_result(stats: dict) -> str:
    """Say why a scan came back empty, so 'nothing found' is never mistaken
    for 'nothing happened'."""
    if not stats or not stats.get("churn_reviews_in_window"):
        return ("No churn-signal reviews in the last "
                f"{stats.get('lookback_days', CHURN_LOOKBACK_DAYS)} days — nothing to act on.")
    if not stats.get("high_value_matches"):
        return (f"{stats['churn_reviews_in_window']} churn-signal review(s) found, but none "
                f"from a customer above the ₹{stats.get('min_ltv_inr', CHURN_MIN_LTV_INR):,} "
                f"lifetime-value line, so a win-back offer would not pay for itself.")
    parts = []
    if stats.get("excluded_recent_offer"):
        parts.append(f"{stats['excluded_recent_offer']} already received an offer in the last "
                     f"{policy.OFFER_FREQUENCY_DAYS} days (frequency cap)")
    if stats.get("excluded_already_proposed"):
        parts.append(f"{stats['excluded_already_proposed']} are already covered by a live "
                     f"proposal or campaign")
    detail = "; ".join(parts) if parts else "all were filtered by the guardrails"
    return (f"{stats['high_value_matches']} high-value customer(s) matched the churn signal, "
            f"but {detail}. The guardrails are holding — nothing new to approve.")


def scan(db, actor: str = "agent", stats: dict | None = None) -> list[Opportunity]:
    """Run a full opportunity scan. Everything it does is audited."""
    entry = audit.write_ahead(db, actor=actor, tool="scan_opportunities",
                              args={"scenario": "churn_risk_winback"},
                              reasoning="Scheduled scan of transaction and feedback "
                                        "signals for revenue opportunities.",
                              verdict=policy.ALLOWED, rule=None)
    try:
        # Behaviour first: it covers every customer. Reviews then add the ones
        # whose words say they are leaving even though they have not yet gone
        # quiet — the two detectors catch different people.
        candidates = [c for c in (detect_lapsed_high_value(db, stats=stats),
                                  detect_churn_risk(db, stats=stats)) if c]
    except Exception as e:
        audit.complete(db, entry, status="failed", error=str(e))
        raise

    if not candidates:
        audit.complete(db, entry, status="success")
        return []

    created: list[Opportunity] = []
    for candidate in candidates:
        created.append(_raise_opportunity(db, candidate, entry))

    audit.complete(db, entry, status="success")
    for opp in created:
        audit.broadcast_opportunity(serialize(opp))
    return created


TITLES = {
    "churn_risk_winback": "{n} high-value customers at risk of churning",
    "lapsed_high_value": "{n} high-value customers have gone quiet",
}

DETECTION_RULES = {
    "churn_risk_winback": (
        f"churn-signal review in the last {CHURN_LOOKBACK_DAYS} days AND "
        f"lifetime spend ≥ ₹{CHURN_MIN_LTV_INR:,}"
    ),
    "lapsed_high_value": (
        f"lifetime spend ≥ ₹{LAPSED_MIN_LTV_INR:,} AND ≥ {LAPSED_MIN_ORDERS} prior orders "
        f"AND silent for ≥ {LAPSED_MIN_SILENT_DAYS} days AND longer than "
        f"{LAPSED_CADENCE_MULTIPLE:g}x their own median gap between orders "
        f"(transactions only — no review required)"
    ),
}


def _raise_opportunity(db, candidate: dict, entry) -> Opportunity:
    """Turn a detector's candidate into a merchant-facing opportunity."""
    rationale = _explain(candidate)

    # The guardrails are consulted BEFORE the merchant ever sees the proposal, so
    # the card can show what would happen rather than promising something the
    # policy engine would refuse.
    verdict, rule = policy.check_proactive(candidate["proposed_tool"],
                                           candidate["proposed_args"], db)

    excluded = candidate["excluded_by_policy"]
    kind = candidate["kind"]
    opp = Opportunity(
        kind=kind,
        title=TITLES[kind].format(n=len(candidate["targets"])),
        rationale=rationale,
        evidence_json=json.dumps({
            "customers": candidate["targets"],
            "assumption_note": ASSUMPTION_NOTE,
            "detection_rule": DETECTION_RULES[kind],
        }),
        customer_ids_json=json.dumps(candidate["proposed_args"]["customer_ids"]),
        revenue_at_risk_inr=candidate["revenue_at_risk_inr"],
        recoverable_revenue_inr=candidate["recoverable_revenue_inr"],
        expected_revenue_inr=candidate["expected_revenue_inr"],
        max_exposure_inr=candidate["max_exposure_inr"],
        assumed_redemption_rate=ASSUMED_REDEMPTION_RATE,
        proposed_tool=candidate["proposed_tool"],
        proposed_args_json=json.dumps(candidate["proposed_args"]),
        policy_verdict=verdict,
        policy_rule_hit=rule,
        excluded_note=(f"{excluded} customer(s) matched the signal but were excluded by "
                       f"the frequency cap or redemption dedupe" if excluded else None),
        status="open",
        audit_id=entry.id,
    )
    db.add(opp)
    db.commit()
    return opp


RETURN_WINDOW_DAYS = 30   # how long after a campaign a return still counts


def _return_rate(db, customer_ids: list[int], since: datetime) -> tuple[int, int]:
    """How many of these customers placed ANY order after `since`.

    Deliberately counts every order, not only ones through our link: a control
    customer has no link, and a treated customer who returns by some other route
    still returned. Anything narrower would flatter the treated group.
    """
    if not customer_ids:
        return 0, 0
    until = since + timedelta(days=RETURN_WINDOW_DAYS)
    returned = 0
    for cid in customer_ids:
        if db.query(Order).filter(Order.customer_id == cid, Order.ts > since,
                                  Order.ts <= until).count():
            returned += 1
    return returned, len(customer_ids)


def incrementality(db, campaign) -> dict | None:
    """Compare the treated group against the held-back control group.

    Attribution proves a payment came through our link. It cannot prove the
    offer caused a return that would have happened anyway. This can — within the
    limits of the sample size, which is reported alongside every figure and
    never hidden.
    """
    control_ids = json.loads(campaign.control_ids_json) if campaign.control_ids_json else []
    if not control_ids:
        return None
    all_ids = json.loads(campaign.customer_ids_json)
    treated_ids = [c for c in all_ids if c not in set(control_ids)]

    t_returned, t_n = _return_rate(db, treated_ids, campaign.ts)
    c_returned, c_n = _return_rate(db, control_ids, campaign.ts)
    t_rate = t_returned / t_n if t_n else 0.0
    c_rate = c_returned / c_n if c_n else 0.0
    return {
        "treated": {"n": t_n, "returned": t_returned, "rate": round(t_rate, 3)},
        "control": {"n": c_n, "returned": c_returned, "rate": round(c_rate, 3)},
        "lift_pct_points": round((t_rate - c_rate) * 100, 1),
        "window_days": RETURN_WINDOW_DAYS,
        "note": (
            "Directional only. The control group received no offer and is measured on "
            "the same window, so this compares like with like — but at these sample "
            "sizes the difference is not statistically significant and must not be "
            "read as a proven effect."
        ),
    }


def measured(db, opp: Opportunity) -> dict:
    """Outcome so far for an executed opportunity (exact, via campaign links)."""
    from .models import Campaign, PaymentLink

    if not opp.campaign_id:
        return {"redeemed": 0, "targeted": len(json.loads(opp.customer_ids_json)),
                "revenue_inr": 0, "incentive_inr": 0}
    links = db.query(PaymentLink).filter_by(campaign_id=opp.campaign_id).all()
    paid = [l for l in links if l.status == "paid"]
    pct = WINBACK_DISCOUNT_PCT
    incentive = sum(int(round(l.amount_inr / (1 - pct / 100) - l.amount_inr)) for l in paid)
    campaign = db.get(Campaign, opp.campaign_id)
    control_ids = (json.loads(campaign.control_ids_json)
                   if campaign and campaign.control_ids_json else [])
    return {
        "targeted": len(links) or len(json.loads(opp.customer_ids_json)),
        "redeemed": len(paid),
        "revenue_inr": sum(l.amount_inr for l in paid),
        "incentive_inr": incentive,
        "control_group_size": len(control_ids),
        "incrementality": incrementality(db, campaign) if campaign else None,
        # razorpay_ref lets anyone verify the object in the Razorpay dashboard —
        # a payment link (plink_) or, once the account's link quota is spent, an
        # order (order_). Persisted, so the card still shows them after a reload.
        "links": [{"customer_id": l.customer_id, "amount_inr": l.amount_inr,
                   "short_url": l.short_url, "status": l.status,
                   "razorpay_ref": l.razorpay_link_id,
                   "paid_ts": utc_iso(l.paid_ts)} for l in links],
    }


def serialize(opp: Opportunity, db=None) -> dict:
    data = {
        "id": opp.id,
        "ts": utc_iso(opp.ts),
        "kind": opp.kind,
        "title": opp.title,
        "rationale": opp.rationale,
        "evidence": json.loads(opp.evidence_json),
        "customer_ids": json.loads(opp.customer_ids_json),
        "revenue_at_risk_inr": opp.revenue_at_risk_inr,
        "recoverable_revenue_inr": opp.recoverable_revenue_inr or 0,
        "expected_revenue_inr": opp.expected_revenue_inr,
        "max_exposure_inr": opp.max_exposure_inr,
        "assumed_redemption_rate": opp.assumed_redemption_rate,
        "proposed_tool": opp.proposed_tool,
        "proposed_args": json.loads(opp.proposed_args_json),
        "policy_verdict": opp.policy_verdict,
        "policy_rule_hit": opp.policy_rule_hit,
        "excluded_note": opp.excluded_note,
        "status": opp.status,
        "campaign_id": opp.campaign_id,
        "approval_id": opp.approval_id,
        "error": opp.error,
        "decided_ts": utc_iso(opp.decided_ts),
    }
    if db is not None:
        data["outcome"] = measured(db, opp)
    return data
