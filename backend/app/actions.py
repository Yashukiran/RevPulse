"""Executors for policy-gated action tools.

Only two call sites exist: the agent loop (for ALLOWED verdicts) and the
approval endpoint (for merchant-approved NEEDS_APPROVAL actions). Both paths
have already passed the policy engine and hold a write-ahead audit entry.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime

from sqlalchemy import func

from . import razorpay_client as rzp
from .models import (
    BudgetSpend,
    Campaign,
    Customer,
    OfferRedemption,
    Order,
    PaymentLink,
    Review,
)


def _aov(db, customer_id: int) -> int:
    v = (db.query(func.avg(Order.amount_inr))
         .filter(Order.customer_id == customer_id).scalar())
    return int(v) if v else 450


def _offer_code(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3).upper()}"


def _make_links(db, campaign: Campaign, customer_ids: list[int], discount_pct: float,
                tool: str, args: dict) -> list[dict]:
    """Create one Razorpay payment link per customer, idempotently."""
    out = []
    for cid in customer_ids:
        cust = db.get(Customer, cid)
        if not cust:
            continue
        key = rzp.idempotency_key(tool, args, discriminator=str(cid))
        existing = db.query(PaymentLink).filter_by(idempotency_key=key).first()
        if existing:  # retry: never double-create
            out.append({"customer_id": cid, "short_url": existing.short_url,
                        "razorpay_link_id": existing.razorpay_link_id,
                        "amount_inr": existing.amount_inr, "reused": True})
            continue
        amount = max(int(round(_aov(db, cid) * (1 - discount_pct / 100))), 1)
        link = rzp.create_payment_link(
            amount_inr=amount,
            description=f"{campaign.offer_desc} — Biryani House (code {campaign.offer_code})",
            customer_name=cust.name, customer_email=cust.email, customer_phone=cust.phone,
            reference_id=key,
            notes={"campaign_id": campaign.id, "offer_code": campaign.offer_code,
                   "customer_id": cid},
        )
        row = PaymentLink(campaign_id=campaign.id, customer_id=cid,
                          razorpay_link_id=link["id"], short_url=link["short_url"],
                          amount_inr=amount, offer_code=campaign.offer_code,
                          idempotency_key=key, status="created")
        db.add(row)
        db.add(OfferRedemption(customer_id=cid, campaign_id=campaign.id))
        out.append({"customer_id": cid, "short_url": link["short_url"],
                    "razorpay_link_id": link["id"], "amount_inr": amount})
    db.commit()
    return out


def create_recovery_offer(db, args: dict) -> dict:
    from .policy import est_offer_value_inr

    customer_ids = [int(c) for c in args["customer_ids"]]
    discount = float(args["discount_pct"])
    campaign = Campaign(
        kind="recovery_offer",
        segment_desc=f"{len(customer_ids)} at-risk customer(s)",
        offer_desc=f"{discount:g}% win-back offer, valid {args.get('expiry_days', 7)} days",
        offer_code=_offer_code("RPREC"),
        discount_pct=discount,
        budget_inr=est_offer_value_inr(args, db) * len(customer_ids),
        customer_ids_json=json.dumps(customer_ids),
    )
    db.add(campaign)
    db.flush()
    links = _make_links(db, campaign, customer_ids, discount, "create_recovery_offer", args)
    db.add(BudgetSpend(date=datetime.utcnow().strftime("%Y-%m-%d"),
                       campaign_id=campaign.id, amount_inr=campaign.budget_inr,
                       note=f"recovery offer {campaign.offer_code}"))
    db.commit()
    return {"campaign_id": campaign.id, "offer_code": campaign.offer_code,
            "links": links, "incentive_budget_inr": campaign.budget_inr}


def create_campaign(db, args: dict) -> dict:
    customer_ids = [int(c) for c in args["customer_ids"]]
    discount = float(args["discount_pct"])
    campaign = Campaign(
        kind="campaign",
        segment_desc=str(args["segment"]),
        offer_desc=str(args["offer"]),
        offer_code=_offer_code("RPCAM"),
        discount_pct=discount,
        budget_inr=int(args["budget_inr"]),
        customer_ids_json=json.dumps(customer_ids),
    )
    db.add(campaign)
    db.flush()
    links = _make_links(db, campaign, customer_ids, discount, "create_campaign", args)
    db.add(BudgetSpend(date=datetime.utcnow().strftime("%Y-%m-%d"),
                       campaign_id=campaign.id, amount_inr=campaign.budget_inr,
                       note=f"campaign {campaign.offer_code}"))
    db.commit()
    return {"campaign_id": campaign.id, "offer_code": campaign.offer_code,
            "links": links, "incentive_budget_inr": campaign.budget_inr}


def create_payment_link(db, args: dict) -> dict:
    cid = int(args["customer_id"])
    cust = db.get(Customer, cid)
    if not cust:
        return {"error": f"customer {cid} not found"}
    key = rzp.idempotency_key("create_payment_link", args)
    existing = db.query(PaymentLink).filter_by(idempotency_key=key).first()
    if existing:
        return {"short_url": existing.short_url, "razorpay_link_id": existing.razorpay_link_id,
                "amount_inr": existing.amount_inr, "reused": True}
    amount = int(args["amount_inr"])
    link = rzp.create_payment_link(
        amount_inr=amount, description="Biryani House order",
        customer_name=cust.name, customer_email=cust.email, customer_phone=cust.phone,
        reference_id=key,
        notes={"customer_id": cid, "offer_code": args.get("offer_code", "")},
    )
    db.add(PaymentLink(customer_id=cid, razorpay_link_id=link["id"],
                       short_url=link["short_url"], amount_inr=amount,
                       offer_code=args.get("offer_code"), idempotency_key=key))
    db.commit()
    return {"short_url": link["short_url"], "razorpay_link_id": link["id"],
            "amount_inr": amount}


def post_reply(db, args: dict) -> dict:
    r = db.get(Review, int(args["review_id"]))
    if not r:
        return {"error": "review not found"}
    r.reply_text = str(args["text"])
    r.reply_posted_ts = datetime.utcnow()
    db.commit()
    return {"review_id": r.id, "posted": True, "posted_ts": r.reply_posted_ts.isoformat()}


EXECUTORS = {
    "create_recovery_offer": create_recovery_offer,
    "create_campaign": create_campaign,
    "create_payment_link": create_payment_link,
    "post_reply": post_reply,
}


def execute_action(db, tool: str, args: dict) -> dict:
    fn = EXECUTORS.get(tool)
    if not fn:
        return {"error": f"unknown action tool {tool}"}
    return fn(db, args)
