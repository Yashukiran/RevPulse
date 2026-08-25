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

    # ---- money maths: deterministic, from this merchant's own transactions ----
    revenue_at_risk = sum(c["ltv_inr"] for c in targets)
    # what each customer would pay on a discounted order
    discounted = [int(round(c["aov_inr"] * (1 - WINBACK_DISCOUNT_PCT / 100))) for c in targets]
    # incentive given away per customer if they redeem
    incentive = [c["aov_inr"] - d for c, d in zip(targets, discounted)]
    max_exposure = sum(incentive)                       # exact worst case: all redeem
    expected_revenue = int(round(sum(discounted) * ASSUMED_REDEMPTION_RATE))

    return {
        "kind": "churn_risk_winback",
        "targets": targets,
        "revenue_at_risk_inr": revenue_at_risk,
        "expected_revenue_inr": expected_revenue,
        "max_exposure_inr": max_exposure,
        "excluded_by_policy": excluded_by_policy,
        "proposed_tool": "create_recovery_offer",
        "proposed_args": {
            "customer_ids": [c["customer_id"] for c in targets],
            "discount_pct": WINBACK_DISCOUNT_PCT,
            "expiry_days": WINBACK_EXPIRY_DAYS,
            "reason": "High-value customers whose recent reviews signal churn",
        },
    }


def _explain(candidate: dict) -> str:
    """One short model call: turn the evidence into a merchant-readable rationale.

    The model receives only figures we computed and may not introduce new ones.
    If the call fails we fall back to a deterministic sentence — the opportunity
    is still fully usable without the model.
    """
    targets = candidate["targets"]
    fallback = (
        f"{len(targets)} high-value customers left churn-signal reviews recently. "
        f"Together they have spent ₹{candidate['revenue_at_risk_inr']:,} with this "
        f"merchant. A {WINBACK_DISCOUNT_PCT}% win-back offer costs at most "
        f"₹{candidate['max_exposure_inr']:,} and targets exactly the customers whose "
        f"repeat business is most valuable to protect."
    )
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        facts = {
            "customers": [
                {"name": t["name"], "ltv_inr": t["ltv_inr"], "aov_inr": t["aov_inr"],
                 "last_order": t["last_order"], "review": t["review"]["text"][:240],
                 "rating": t["review"]["rating"]}
                for t in targets[:6]
            ],
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
                "Write 2-3 sentences for the merchant explaining what you found, quoting "
                "one customer's words as evidence, and why acting now protects revenue. "
                "Use ONLY the figures given — never invent a number. Plain language, no "
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
        candidate = detect_churn_risk(db, stats=stats)
    except Exception as e:
        audit.complete(db, entry, status="failed", error=str(e))
        raise

    if not candidate:
        audit.complete(db, entry, status="success")
        return []

    rationale = _explain(candidate)

    # The guardrails are consulted BEFORE the merchant ever sees the proposal, so
    # the card can show what would happen rather than promising something the
    # policy engine would refuse.
    verdict, rule = policy.check_proactive(candidate["proposed_tool"],
                                           candidate["proposed_args"], db)

    excluded = candidate["excluded_by_policy"]
    opp = Opportunity(
        kind=candidate["kind"],
        title=f"{len(candidate['targets'])} high-value customers at risk of churning",
        rationale=rationale,
        evidence_json=json.dumps({
            "customers": candidate["targets"],
            "assumption_note": ASSUMPTION_NOTE,
            "detection_rule": (
                f"churn-signal review in the last {CHURN_LOOKBACK_DAYS} days AND "
                f"lifetime spend ≥ ₹{CHURN_MIN_LTV_INR:,}"
            ),
        }),
        customer_ids_json=json.dumps(candidate["proposed_args"]["customer_ids"]),
        revenue_at_risk_inr=candidate["revenue_at_risk_inr"],
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
    audit.complete(db, entry, status="success")
    audit.broadcast_opportunity(serialize(opp))
    return [opp]


def measured(db, opp: Opportunity) -> dict:
    """Outcome so far for an executed opportunity (exact, via campaign links)."""
    from .models import PaymentLink

    if not opp.campaign_id:
        return {"redeemed": 0, "targeted": len(json.loads(opp.customer_ids_json)),
                "revenue_inr": 0, "incentive_inr": 0}
    links = db.query(PaymentLink).filter_by(campaign_id=opp.campaign_id).all()
    paid = [l for l in links if l.status == "paid"]
    pct = WINBACK_DISCOUNT_PCT
    incentive = sum(int(round(l.amount_inr / (1 - pct / 100) - l.amount_inr)) for l in paid)
    return {
        "targeted": len(links) or len(json.loads(opp.customer_ids_json)),
        "redeemed": len(paid),
        "revenue_inr": sum(l.amount_inr for l in paid),
        "incentive_inr": incentive,
        "links": [{"customer_id": l.customer_id, "amount_inr": l.amount_inr,
                   "short_url": l.short_url, "status": l.status} for l in links],
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
