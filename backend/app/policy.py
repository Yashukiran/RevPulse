"""Deterministic policy engine. Pure Python, zero LLM involvement.

The agent can ASK for anything; only this module decides what is ALLOWED,
what is parked for merchant approval, and what is BLOCKED outright. Every
rule here is listed in the README and defended in the audit trail.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func

from .models import Approval, BudgetSpend, OfferRedemption, Order

ALLOWED = "ALLOWED"
NEEDS_APPROVAL = "NEEDS_APPROVAL"
BLOCKED = "BLOCKED"

# ---- hard bounds (money) ----
MAX_DISCOUNT_PCT = 20
MAX_RECOVERY_VALUE_INR = 300          # per customer
DAILY_BUDGET_INR = 5000
CAMPAIGN_CAP_INR = 2000

# ---- approval thresholds ----
APPROVAL_OFFER_VALUE_INR = 150        # any offer above this needs a human
APPROVAL_SEGMENT_SIZE = 25            # any segment above this needs a human

# ---- customer protection ----
OFFER_FREQUENCY_DAYS = 30             # max 1 offer per customer per 30 days

# ---- proactive agent ----
# An agent spending money on its own initiative is a different risk class from
# one executing something the merchant just asked for, so proposals it raises
# unprompted always go to the merchant — even when every other bound is clear.
# Set False to let small, fully-compliant proposals execute automatically.
PROACTIVE_REQUIRES_APPROVAL = True

READ_OR_DRAFT = {
    "get_reviews", "get_review_stats", "get_customers", "get_customer_history",
    "get_transactions", "get_campaign_results", "draft_reply",
}
FORBIDDEN_TOOLS = {"refund", "create_refund", "withdraw", "payout", "update_payout",
                   "change_bank_account"}  # defense in depth: these tools don't even exist


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _spent_today(db) -> int:
    rows = db.query(BudgetSpend).filter(BudgetSpend.date == _today()).all()
    return sum(r.amount_inr for r in rows)


def _recent_offer_customers(db) -> set[int]:
    cutoff = datetime.utcnow() - timedelta(days=OFFER_FREQUENCY_DAYS)
    return {r.customer_id for r in db.query(OfferRedemption)
            .filter(OfferRedemption.sent_ts >= cutoff)}


def _redeemed_customers(db) -> set[int]:
    return {r.customer_id for r in db.query(OfferRedemption)
            .filter(OfferRedemption.redeemed_ts.isnot(None))}


def check(tool: str, args: dict, db) -> tuple[str, str | None]:
    """Return (verdict, rule_hit). Deterministic; order: BLOCKED > NEEDS_APPROVAL > ALLOWED."""
    args = args or {}

    if tool in FORBIDDEN_TOOLS:
        return BLOCKED, "forbidden-action: refunds/withdrawals/payout changes are never agent actions"

    if tool in READ_OR_DRAFT:
        return ALLOWED, None

    if tool == "post_reply":
        return NEEDS_APPROVAL, "external-action: posting publicly always requires merchant approval"

    if tool in {"create_recovery_offer", "create_campaign", "create_payment_link"}:
        discount = float(args.get("discount_pct") or 0)
        if discount > MAX_DISCOUNT_PCT:
            return BLOCKED, f"max-discount: {discount}% > {MAX_DISCOUNT_PCT}% cap"

        customer_ids = list(args.get("customer_ids") or
                            ([args["customer_id"]] if args.get("customer_id") else []))

        # customer protection: frequency cap + redeemed dedupe
        if customer_ids:
            recent = _recent_offer_customers(db) & set(customer_ids)
            if recent:
                return BLOCKED, (f"frequency-cap: customers {sorted(recent)} already received an "
                                 f"offer in the last {OFFER_FREQUENCY_DAYS} days")
            redeemed = _redeemed_customers(db) & set(customer_ids)
            if redeemed:
                return BLOCKED, (f"dedupe: customers {sorted(redeemed)} already redeemed an offer "
                                 f"and cannot be re-targeted")

        # budget maths
        if tool == "create_campaign":
            budget = int(args.get("budget_inr") or 0)
            if budget > CAMPAIGN_CAP_INR:
                return BLOCKED, f"campaign-cap: ₹{budget} > ₹{CAMPAIGN_CAP_INR} per-campaign cap"
            if _spent_today(db) + budget > DAILY_BUDGET_INR:
                return BLOCKED, (f"daily-budget: ₹{_spent_today(db)} spent + ₹{budget} requested "
                                 f"> ₹{DAILY_BUDGET_INR}/day")
            return NEEDS_APPROVAL, "campaign: any campaign requires merchant approval"

        if tool == "create_recovery_offer":
            est_value = est_offer_value_inr(args, db)
            if est_value > MAX_RECOVERY_VALUE_INR:
                return BLOCKED, (f"recovery-value: est. ₹{est_value}/customer > "
                                 f"₹{MAX_RECOVERY_VALUE_INR} cap")
            total_est = est_value * max(len(customer_ids), 1)
            if _spent_today(db) + total_est > DAILY_BUDGET_INR:
                return BLOCKED, (f"daily-budget: ₹{_spent_today(db)} spent + est. ₹{total_est} "
                                 f"> ₹{DAILY_BUDGET_INR}/day")
            if len(customer_ids) > APPROVAL_SEGMENT_SIZE:
                return NEEDS_APPROVAL, f"segment-size: {len(customer_ids)} > {APPROVAL_SEGMENT_SIZE} customers"
            if est_value > APPROVAL_OFFER_VALUE_INR:
                return NEEDS_APPROVAL, f"offer-value: est. ₹{est_value} > ₹{APPROVAL_OFFER_VALUE_INR}"
            return ALLOWED, None

        if tool == "create_payment_link":
            amount = int(args.get("amount_inr") or 0)
            if amount <= 0:
                return BLOCKED, "invalid-amount: payment link amount must be positive"
            if len(customer_ids) > APPROVAL_SEGMENT_SIZE:
                return NEEDS_APPROVAL, f"segment-size: {len(customer_ids)} > {APPROVAL_SEGMENT_SIZE}"
            return ALLOWED, None

    return BLOCKED, f"unknown-tool: '{tool}' is not a registered action"


DEFAULT_AOV_INR = 450  # fallback when a customer has no order history


def check_proactive(tool: str, args: dict, db) -> tuple[str, str | None]:
    """Verdict for an action the agent raised on its own initiative.

    Identical to check(), except that a clean ALLOWED is still escalated to the
    merchant when PROACTIVE_REQUIRES_APPROVAL is on. Blocks stay blocks.
    """
    verdict, rule = check(tool, args, db)
    if verdict == ALLOWED and PROACTIVE_REQUIRES_APPROVAL:
        return NEEDS_APPROVAL, ("agent-initiated: proposals the agent raises on its own "
                                "always require merchant approval")
    return verdict, rule


def est_offer_value_inr(args: dict, db=None) -> int:
    """Estimated incentive cost per customer: discount% of the most expensive
    targeted customer's average order value (worst case bounds the whole batch).
    Deterministic — same inputs, same estimate."""
    discount = float(args.get("discount_pct") or 0)
    aov = DEFAULT_AOV_INR
    customer_ids = list(args.get("customer_ids") or [])
    if db is not None and customer_ids:
        rows = (db.query(func.avg(Order.amount_inr))
                .filter(Order.customer_id.in_(customer_ids))
                .group_by(Order.customer_id).all())
        if rows:
            aov = max(float(r[0]) for r in rows)
    return int(round(aov * discount / 100))


def queue_approval(db, audit_entry, tool: str, args: dict, reasoning: str) -> dict:
    """Park a NEEDS_APPROVAL action for the merchant. Returns the tool_result payload."""
    ap = Approval(audit_id=audit_entry.id, tool=tool, args_json=json.dumps(args),
                  agent_reasoning=reasoning, status="pending")
    db.add(ap)
    db.commit()
    return {
        "verdict": NEEDS_APPROVAL,
        "approval_id": ap.id,
        "note": ("Parked for merchant approval. It will execute only if the merchant approves "
                 "in the dashboard. Continue with your other work; do not retry this action."),
    }
