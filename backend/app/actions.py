"""Executors for policy-gated action tools.

Only two call sites exist: the agent loop (for ALLOWED verdicts) and the
approval endpoint (for merchant-approved NEEDS_APPROVAL actions). Both paths
have already passed the policy engine and hold a write-ahead audit entry.
"""

from __future__ import annotations

import json
import random
import secrets
import time
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


RATE_LIMIT_BACKOFF_S = (1.0, 3.0, 8.0, 20.0)


def _create_link(*, reference_id: str, **kw) -> dict:
    """Create a Razorpay payment link, handling the two provider-side failures
    that are not our caller's fault.

    1. Reference already used — our own ledger is the idempotency authority: if
       we hold a row for this key we never get here. Reaching this path means
       our ledger lost the record (e.g. the demo-state reset), so we mint a
       fresh reference and still store it under the original key.
    2. Rate limiting — retry with backoff rather than failing the campaign.
    """
    ref = reference_id
    last: Exception | None = None
    for attempt in range(len(RATE_LIMIT_BACKOFF_S) + 1):
        try:
            return rzp.create_payment_link(reference_id=ref, **kw)
        except Exception as e:
            last = e
            msg = str(e).lower()
            if "reference" in msg and "exist" in msg:
                ref = f"{reference_id[:24]}-{secrets.token_hex(3)}"
                continue
            # Razorpay test mode allows 30 payment links per account, for the
            # life of the account. Past that we create a real Razorpay ORDER
            # instead — the object an in-app checkout uses — so the money loop
            # keeps working and attribution is unchanged.
            if "limit of 30" in msg or "test mode limit" in msg:
                order = rzp.create_order(
                    amount_inr=kw["amount_inr"], reference_id=ref,
                    notes=kw.get("notes", {}),
                )
                return {"id": order["id"], "short_url": "", "kind": "order"}
            transient = (
                "too many requests" in msg or "rate limit" in msg or "429" in msg
                or "connection" in msg or "timed out" in msg or "timeout" in msg
                or isinstance(e, (ConnectionError, TimeoutError))
            )
            if transient and attempt < len(RATE_LIMIT_BACKOFF_S):
                time.sleep(RATE_LIMIT_BACKOFF_S[attempt])
                continue
            raise
    raise last  # exhausted retries


# Below this segment size a holdout is statistically meaningless — splitting
# three people into treated and control tells you nothing — so we skip it and
# say so rather than producing a number that looks like evidence.
HOLDOUT_MIN_SEGMENT = 6
HOLDOUT_SHARE = 0.30


def split_holdout(customer_ids: list[int], campaign_id: int) -> tuple[list[int], list[int]]:
    """Split a segment into treated and control.

    Without a control group we can only prove a payment came through our link
    (attribution); we cannot show the offer caused a return that would not have
    happened anyway. Holding a share of the segment back — same profile, no
    offer — is what makes that difference measurable.

    The split is seeded off the campaign id, so it is reproducible and cannot be
    quietly re-rolled until the result looks better.
    """
    if len(customer_ids) < HOLDOUT_MIN_SEGMENT:
        return list(customer_ids), []
    rng = random.Random(f"holdout-{campaign_id}")
    shuffled = sorted(customer_ids)
    rng.shuffle(shuffled)
    n_control = max(1, int(round(len(shuffled) * HOLDOUT_SHARE)))
    control = sorted(shuffled[:n_control])
    treated = sorted(shuffled[n_control:])
    return treated, control


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
    for i, cid in enumerate(customer_ids):
        if i:
            time.sleep(0.25)  # stagger: stay under the provider's burst limit
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
        try:
            link = _create_link(
                amount_inr=amount,
                description=f"{campaign.offer_desc} — Biryani House (code {campaign.offer_code})",
                customer_name=cust.name, customer_email=cust.email, customer_phone=cust.phone,
                reference_id=key,
                notes={"campaign_id": campaign.id, "offer_code": campaign.offer_code,
                       "customer_id": cid},
            )
        except Exception as e:
            # One customer's link failing must not abandon the batch. Aborting
            # here used to leave the customers already reached marked as offered
            # while the campaign as a whole failed — and the frequency cap then
            # blocked the retry, so a partial failure poisoned its own recovery.
            # Record the failure against that customer and carry on.
            out.append({"customer_id": cid, "error": str(e)[:200]})
            continue
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

    # Hold a share of the segment back with no offer, so the campaign can be
    # measured against customers who were treated identically apart from the
    # intervention itself.
    treated, control = split_holdout(customer_ids, campaign.id)
    campaign.control_ids_json = json.dumps(control) if control else None
    campaign.budget_inr = est_offer_value_inr(args, db) * len(treated)

    links = _make_links(db, campaign, treated, discount, "create_recovery_offer", args)
    reached = [l for l in links if not l.get("error")]
    failed = [l for l in links if l.get("error")]
    if not reached:
        raise RuntimeError(failed[0]["error"] if failed else "no payment links created")

    # Budget reserves against the customers actually reached, not the ones we
    # intended to reach.
    campaign.budget_inr = est_offer_value_inr(args, db) * len(reached)
    db.add(BudgetSpend(date=datetime.utcnow().strftime("%Y-%m-%d"),
                       campaign_id=campaign.id, amount_inr=campaign.budget_inr,
                       note=f"recovery offer {campaign.offer_code}"))
    db.commit()
    return {"campaign_id": campaign.id, "offer_code": campaign.offer_code,
            "links": reached, "incentive_budget_inr": campaign.budget_inr,
            "failed": failed,
            "treated": len(reached), "control": len(control),
            "holdout_note": (f"{len(control)} of {len(customer_ids)} customers held back as a "
                             f"control group to measure incrementality"
                             if control else
                             f"segment of {len(customer_ids)} is below the {HOLDOUT_MIN_SEGMENT}-"
                             f"customer minimum for a meaningful holdout; attribution only")}


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
    link = _create_link(
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
