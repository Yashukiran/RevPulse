"""Agent tools: JSON schemas given to Claude + their executors.

Read-only and drafting tools execute directly. Money/action tools are defined
here but ALWAYS pass through the policy engine before execution (wired in
policy/audit layers) — the LLM can only request them.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func

from .. import aggregates
from ..db import SessionLocal
from ..models import Campaign, Customer, Order, PaymentLink, Review

DRAFT_MODEL = "claude-haiku-4-5-20251001"

# ------------------------------------------------------------------ schemas

TOOLS = [
    {
        "name": "get_review_stats",
        "description": "Aggregate review intelligence: totals, rating/sentiment distribution, theme counts, per-theme monthly trend, per-theme time-of-day and zone concentration. Start here.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_reviews",
        "description": "Fetch reviews, filterable by theme, sentiment, urgency, churn_signal, month (YYYY-MM). Returns id, ts, rating, text, customer_id, themes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "theme": {"type": "string"},
                "sentiment": {"type": "string"},
                "urgency": {"type": "string"},
                "churn_signal": {"type": "boolean"},
                "month": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
            },
            "required": [],
        },
    },
    {
        "name": "get_customers",
        "description": "Customer segments with LTV (total spend), order count, last order date, zone. Filter by min_ltv_inr, churn_signal (has churn-risk review), zone, inactive_days (no order in N days).",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_ltv_inr": {"type": "integer"},
                "churn_signal": {"type": "boolean"},
                "zone": {"type": "string"},
                "inactive_days": {"type": "integer"},
                "limit": {"type": "integer", "default": 25},
            },
            "required": [],
        },
    },
    {
        "name": "get_customer_history",
        "description": "Full history for one customer: profile, all orders, all reviews.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": {"type": "integer"}},
            "required": ["customer_id"],
        },
    },
    {
        "name": "get_transactions",
        "description": "Transaction aggregates: monthly revenue and order counts, top items by revenue, repeat-purchase comparison for customers mentioning a given theme vs others (association with sample sizes).",
        "input_schema": {
            "type": "object",
            "properties": {"compare_theme": {"type": "string"}},
            "required": [],
        },
    },
    {
        "name": "get_campaign_results",
        "description": "All campaigns with targeted count, links created, redemptions, revenue attributed via unique offer codes, incentive cost.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "draft_reply",
        "description": "Draft a reply to a review in a given tone. Nothing is posted — drafting only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "review_id": {"type": "integer"},
                "tone": {"type": "string", "enum": ["professional", "friendly", "premium"]},
            },
            "required": ["review_id", "tone"],
        },
    },
    # ---- money/action tools: request-only, policy-gated (executors wired in Phase 4)
    {
        "name": "create_recovery_offer",
        "description": "Create a personal win-back offer (unique Razorpay payment link + offer code) for specific at-risk customers. GATED: goes through the policy engine and may require merchant approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_ids": {"type": "array", "items": {"type": "integer"}},
                "discount_pct": {"type": "number"},
                "expiry_days": {"type": "integer"},
                "reason": {"type": "string", "description": "Plain-language why, shown to the merchant"},
            },
            "required": ["customer_ids", "discount_pct", "expiry_days", "reason"],
        },
    },
    {
        "name": "create_campaign",
        "description": "Create a promotional campaign (unique offer code + payment links) for a customer segment. GATED: always requires merchant approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "segment": {"type": "string", "description": "e.g. 'lapsed 60d customers in Whitefield'"},
                "customer_ids": {"type": "array", "items": {"type": "integer"}},
                "offer": {"type": "string", "description": "e.g. '15% off Mutton Dum Biryani'"},
                "discount_pct": {"type": "number"},
                "budget_inr": {"type": "integer"},
            },
            "required": ["segment", "customer_ids", "offer", "discount_pct", "budget_inr"],
        },
    },
    {
        "name": "create_payment_link",
        "description": "Create one Razorpay payment link for a customer. GATED by policy.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_id": {"type": "integer"},
                "amount_inr": {"type": "integer"},
                "offer_code": {"type": "string"},
            },
            "required": ["customer_id", "amount_inr"],
        },
    },
    {
        "name": "post_reply",
        "description": "Publish a reply to a review on the store page. GATED: external action, always requires merchant approval.",
        "input_schema": {
            "type": "object",
            "properties": {"review_id": {"type": "integer"}, "text": {"type": "string"}},
            "required": ["review_id", "text"],
        },
    },
]

READ_TOOLS = {"get_review_stats", "get_reviews", "get_customers", "get_customer_history",
              "get_transactions", "get_campaign_results"}
DRAFT_TOOLS = {"draft_reply"}
ACTION_TOOLS = {"create_recovery_offer", "create_campaign", "create_payment_link", "post_reply"}

# ------------------------------------------------------------------ executors


def _themes(r: Review) -> list[str]:
    return json.loads(r.themes_json) if r.themes_json else []


def get_review_stats(db, **_) -> dict:
    # Read the five columns this needs as plain tuples rather than hydrating
    # full Review objects, and resolve zones from one customer query. Touching
    # r.customer per review lazy-loaded a row each time — 789 extra round trips
    # for a function that only ever needed the zone string.
    rows = db.query(
        Review.ts, Review.rating, Review.sentiment, Review.themes_json,
        Review.customer_id,
    ).all()
    zone_of = dict(db.query(Customer.id, Customer.zone).all())

    by_rating = Counter(r.rating for r in rows)
    by_sentiment = Counter(r.sentiment or "unextracted" for r in rows)
    theme_total: Counter = Counter()
    theme_month: dict[str, Counter] = defaultdict(Counter)
    theme_dow_evening: dict[str, Counter] = defaultdict(Counter)
    theme_zone: dict[str, Counter] = defaultdict(Counter)
    DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
    for ts, _rating, _sentiment, themes_json, customer_id in rows:
        month = ts.strftime("%Y-%m")
        slot = f"{DAYS[ts.weekday()]} {'7-10PM' if 19 <= ts.hour <= 22 else 'other'}"
        zone = zone_of.get(customer_id)
        for t in json.loads(themes_json) if themes_json else ():
            theme_total[t] += 1
            theme_month[t][month] += 1
            theme_dow_evening[t][slot] += 1
            if zone:
                theme_zone[t][zone] += 1
    return {
        "total_reviews": len(rows),
        "rating_distribution": dict(by_rating),
        "sentiment_distribution": dict(by_sentiment),
        "theme_counts": dict(theme_total.most_common()),
        "theme_monthly_trend": {t: dict(sorted(c.items())) for t, c in theme_month.items()},
        "theme_time_concentration": {t: dict(c.most_common(5)) for t, c in theme_dow_evening.items()},
        "theme_zone_distribution": {t: dict(c.most_common()) for t, c in theme_zone.items()},
    }


def get_reviews(db, theme=None, sentiment=None, urgency=None, churn_signal=None,
                month=None, limit=25, **_) -> dict:
    q = db.query(Review)
    if sentiment:
        q = q.filter(Review.sentiment == sentiment)
    if urgency:
        q = q.filter(Review.urgency == urgency)
    if churn_signal is not None:
        q = q.filter(Review.churn_signal == churn_signal)
    rows = q.order_by(Review.ts.desc()).all()
    if theme:
        rows = [r for r in rows if theme in _themes(r)]
    if month:
        rows = [r for r in rows if r.ts.strftime("%Y-%m") == month]
    total = len(rows)
    rows = rows[: min(int(limit or 25), 50)]
    return {
        "matched": total,
        "reviews": [
            {"id": r.id, "ts": r.ts.isoformat(), "rating": r.rating, "text": r.text,
             "customer_id": r.customer_id, "themes": _themes(r), "urgency": r.urgency,
             "churn_signal": r.churn_signal}
            for r in rows
        ],
    }


def _ltv_map(db) -> dict[int, int]:
    return dict(
        db.query(Order.customer_id, func.sum(Order.amount_inr)).group_by(Order.customer_id)
    )


def get_customers(db, min_ltv_inr=None, churn_signal=None, zone=None,
                  inactive_days=None, limit=25, **_) -> dict:
    from datetime import datetime

    ltv = _ltv_map(db)
    last_order = dict(db.query(Order.customer_id, func.max(Order.ts)).group_by(Order.customer_id))
    n_orders = dict(db.query(Order.customer_id, func.count()).group_by(Order.customer_id))
    churn_ids = {r.customer_id for r in db.query(Review).filter(Review.churn_signal.is_(True))}
    ref_now = max(last_order.values()) if last_order else datetime.utcnow()

    out = []
    for c in db.query(Customer).all():
        if min_ltv_inr and ltv.get(c.id, 0) < min_ltv_inr:
            continue
        if churn_signal is not None and (c.id in churn_ids) != churn_signal:
            continue
        if zone and c.zone != zone:
            continue
        if inactive_days:
            lo = last_order.get(c.id)
            if lo and (ref_now - lo).days < inactive_days:
                continue
        out.append({
            "customer_id": c.id, "name": c.name, "zone": c.zone,
            "ltv_inr": int(ltv.get(c.id, 0)), "orders": n_orders.get(c.id, 0),
            "last_order": last_order[c.id].isoformat() if c.id in last_order else None,
            "churn_signal_review": c.id in churn_ids,
        })
    out.sort(key=lambda x: -x["ltv_inr"])
    return {"matched": len(out), "customers": out[: min(int(limit or 25), 60)]}


def get_customer_history(db, customer_id: int, **_) -> dict:
    c = db.get(Customer, customer_id)
    if not c:
        return {"error": f"customer {customer_id} not found"}
    orders = db.query(Order).filter_by(customer_id=customer_id).order_by(Order.ts).all()
    return {
        "customer": {"id": c.id, "name": c.name, "zone": c.zone, "email": c.email,
                     "first_seen": c.first_seen.isoformat()},
        "ltv_inr": sum(o.amount_inr for o in orders),
        "orders": [{"id": o.id, "ts": o.ts.isoformat(), "amount_inr": o.amount_inr,
                    "items": json.loads(o.items_json)} for o in orders],
        "reviews": [{"id": r.id, "ts": r.ts.isoformat(), "rating": r.rating, "text": r.text,
                     "themes": _themes(r), "churn_signal": r.churn_signal}
                    for r in c.reviews],
    }


def get_transactions(db, compare_theme=None, **_) -> dict:
    # Read the shared single-pass aggregate rather than re-scanning and
    # re-parsing every basket on each request.
    agg = aggregates.build(db)
    monthly = agg.monthly
    item_rev = agg.item_revenue
    result = {
        "monthly": dict(sorted(monthly.items())),
        "top_items_by_revenue": dict(item_rev.most_common(10)),
    }
    if compare_theme:
        WINDOW = timedelta(days=45)
        theme_cust, other_cust = set(), set()
        latest_review: dict[int, Review] = {}
        for r in db.query(Review).order_by(Review.ts):
            latest_review[r.customer_id] = r
            (theme_cust if compare_theme in _themes(r) else other_cust).add(r.customer_id)
        other_cust -= theme_cust

        # One pass over the order timestamps of everyone who reviewed, instead
        # of a COUNT query per customer. Same definition of "repeated": at
        # least one order inside the 45-day window after their latest review.
        reviewer_ids = theme_cust | other_cust
        repeated: set[int] = set()
        if reviewer_ids:
            for cid, ts in db.query(Order.customer_id, Order.ts).filter(
                Order.customer_id.in_(reviewer_ids)
            ).all():
                if cid in repeated:
                    continue
                rv_ts = latest_review[cid].ts
                if rv_ts < ts <= rv_ts + WINDOW:
                    repeated.add(cid)

        def repeat_rate(ids: set[int]) -> float:
            if not ids:
                return 0.0
            return round(len(ids & repeated) / len(ids), 3)

        result["repeat_purchase_comparison"] = {
            "theme": compare_theme,
            "note": "ASSOCIATION, not causation. Repeat = new order within 45 days of latest review.",
            "customers_mentioning_theme": {"n": len(theme_cust), "repeat_rate": repeat_rate(theme_cust)},
            "other_reviewers": {"n": len(other_cust), "repeat_rate": repeat_rate(other_cust)},
        }
    return result


def get_campaign_results(db, **_) -> dict:
    out = []
    for c in db.query(Campaign).order_by(Campaign.ts.desc()).all():
        links = db.query(PaymentLink).filter_by(campaign_id=c.id).all()
        paid = [l for l in links if l.status == "paid"]
        # The incentive is only actually paid when a customer redeems: the
        # discount given away on that order. Budget is what policy RESERVED.
        pct = float(c.discount_pct or 0)
        spent = sum(
            int(round(l.amount_inr / (1 - pct / 100) - l.amount_inr)) if pct < 100 else 0
            for l in paid
        )
        out.append({
            "campaign_id": c.id, "kind": c.kind, "segment": c.segment_desc,
            "offer": c.offer_desc, "offer_code": c.offer_code, "status": c.status,
            "targeted": len(json.loads(c.customer_ids_json)),
            "links_created": len(links), "redeemed": len(paid),
            "revenue_attributed_inr": sum(l.amount_inr for l in paid),
            "incentive_spent_inr": spent,
            "incentive_budget_inr": c.budget_inr,
        })
    return {"campaigns": out}


def draft_reply(db, review_id: int, tone: str, **_) -> dict:
    import anthropic

    r = db.get(Review, review_id)
    if not r:
        return {"error": f"review {review_id} not found"}
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = client.messages.create(
        model=DRAFT_MODEL,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": (
                f"You reply to customer reviews for The Nandana Palace, a Bengaluru restaurant. "
                f"Tone: {tone}. Max 3 sentences, specific to their feedback, no fake promises, "
                f"sign off as 'Team Nandana Palace'.\n\nReview ({r.rating}/5): {r.text}\n\n"
                f"Reply with only the reply text."
            ),
        }],
    )
    draft = msg.content[0].text.strip()
    r.reply_text = draft
    db.commit()
    return {"review_id": review_id, "tone": tone, "draft": draft,
            "note": "Draft saved. Posting publicly requires the gated post_reply action."}


EXECUTORS = {
    "get_review_stats": get_review_stats,
    "get_reviews": get_reviews,
    "get_customers": get_customers,
    "get_customer_history": get_customer_history,
    "get_transactions": get_transactions,
    "get_campaign_results": get_campaign_results,
    "draft_reply": draft_reply,
}


def execute_tool(name: str, args: dict, db=None) -> dict:
    """Run a read/draft tool. Action tools are executed by the action layer, not here."""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        fn = EXECUTORS.get(name)
        if not fn:
            return {"error": f"tool {name} has no direct executor (action tools are policy-gated)"}
        return fn(db, **(args or {}))
    finally:
        if own:
            db.close()
