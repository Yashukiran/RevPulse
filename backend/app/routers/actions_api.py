"""Approvals, agent runs, and Razorpay webhooks."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import actions, audit
from ..agent.loop import run_agent
from ..db import get_db
from ..models import Approval, AuditLog, OfferRedemption, Opportunity, Order, PaymentLink
from ..razorpay_client import verify_webhook_signature

router = APIRouter()


# ------------------------------------------------------------- agent


class AgentIn(BaseModel):
    message: str


@router.post("/api/agent/run")
def agent_run(body: AgentIn):
    """Run one agent conversation (sync worker thread; audit streams live via WS)."""
    result = run_agent(body.message)
    return {"text": result["text"], "tool_events": result["tool_events"]}


# ------------------------------------------------------------- approvals


@router.post("/api/approvals/{approval_id}/approve")
def approve(approval_id: int, db: Session = Depends(get_db)):
    ap = db.get(Approval, approval_id)
    if not ap:
        raise HTTPException(404, "approval not found")
    if ap.status != "pending":
        raise HTTPException(409, f"approval already {ap.status}")

    entry = db.get(AuditLog, ap.audit_id)
    args = json.loads(ap.args_json)
    ap.status = "approved"
    ap.decided_ts = datetime.utcnow()
    db.commit()

    # merchant approval recorded -> execute through the same executor path
    exec_entry = audit.write_ahead(db, actor="merchant", tool=ap.tool, args=args,
                                   reasoning=f"approved request #{ap.id} (agent: "
                                             f"{(ap.agent_reasoning or '')[:200]})",
                                   verdict="ALLOWED",
                                   rule=f"merchant-approved:{ap.id}")
    try:
        result = actions.execute_action(db, ap.tool, args)
        ref = None
        if isinstance(result, dict):
            ref = (result.get("links") or [{}])[0].get("razorpay_link_id") \
                if result.get("links") else result.get("razorpay_link_id")
        audit.complete(db, exec_entry, status="success", razorpay_ref=ref)
        if entry:
            audit.complete(db, entry, status="success", razorpay_ref=ref)
        return {"approved": True, "result": result}
    except Exception as e:
        audit.complete(db, exec_entry, status="failed", error=str(e))
        if entry:
            audit.complete(db, entry, status="failed", error=str(e))
        # graceful failure: report, never crash; the agent/merchant can retry —
        # idempotency keys guarantee no double-create on retry
        return {"approved": True, "result": {"error": str(e)},
                "note": "execution failed; safe to retry (idempotent)"}


@router.post("/api/approvals/{approval_id}/reject")
def reject(approval_id: int, db: Session = Depends(get_db)):
    ap = db.get(Approval, approval_id)
    if not ap:
        raise HTTPException(404, "approval not found")
    if ap.status != "pending":
        raise HTTPException(409, f"approval already {ap.status}")
    ap.status = "rejected"
    ap.decided_ts = datetime.utcnow()
    db.commit()
    entry = db.get(AuditLog, ap.audit_id)
    if entry:
        audit.complete(db, entry, status="blocked", error="merchant rejected")
    return {"rejected": True}


# ------------------------------------------------------------- webhooks / attribution


def _mark_link(db, link: PaymentLink, outcome: str, payment_id: str | None) -> dict:
    if outcome == "paid":
        if link.status == "paid":     # webhook retries are idempotent too
            return {"already": True}
        link.status = "paid"
        link.paid_ts = datetime.utcnow()
        link.razorpay_payment_id = payment_id
        # exact attribution: the resulting order carries the campaign id
        db.add(Order(customer_id=link.customer_id, ts=link.paid_ts,
                     amount_inr=link.amount_inr,
                     items_json=json.dumps([{"item": f"Offer {link.offer_code}",
                                             "qty": 1, "price_inr": link.amount_inr}]),
                     zone="", status="paid", campaign_id=link.campaign_id))
        red = (db.query(OfferRedemption)
               .filter_by(customer_id=link.customer_id, campaign_id=link.campaign_id)
               .first())
        if red:
            red.redeemed_ts = link.paid_ts
    else:
        link.status = "failed"
    db.commit()
    # Close the loop: attribute the payment back to the opportunity that caused it.
    opp = (db.query(Opportunity).filter_by(campaign_id=link.campaign_id).first()
           if link.campaign_id else None)
    entry = audit.write_ahead(db, actor="system", tool=f"webhook:payment.{outcome}",
                              args={"razorpay_link_id": link.razorpay_link_id,
                                    "payment_id": payment_id,
                                    "amount_inr": link.amount_inr,
                                    "campaign_id": link.campaign_id,
                                    "opportunity_id": opp.id if opp else None},
                              reasoning=(f"Payment attributed to opportunity #{opp.id} "
                                         f"via its unique campaign link" if opp else None),
                              verdict="ALLOWED", rule=None)
    audit.complete(db, entry, status="success", razorpay_ref=payment_id)
    if opp:
        from .. import opportunities as _opps
        audit.broadcast_opportunity(_opps.serialize(opp, db))
    return {"attributed_campaign_id": link.campaign_id, "amount_inr": link.amount_inr,
            "attributed_opportunity_id": opp.id if opp else None}


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not verify_webhook_signature(body, signature):
        raise HTTPException(400, "invalid signature")
    event = json.loads(body)
    kind = event.get("event", "")
    if kind in {"payment_link.paid", "payment_link.expired", "payment.failed"}:
        entity = (event.get("payload", {}).get("payment_link", {}).get("entity")
                  or event.get("payload", {}).get("payment", {}).get("entity") or {})
        link_id = entity.get("id") or entity.get("link_id")
        payment_id = (event.get("payload", {}).get("payment", {}).get("entity", {})
                      .get("id"))
        link = db.query(PaymentLink).filter_by(razorpay_link_id=link_id).first()
        if link:
            outcome = "paid" if kind == "payment_link.paid" else "failed"
            return _mark_link(db, link, outcome, payment_id)
    return {"ignored": kind}


class SimulateIn(BaseModel):
    razorpay_link_id: str
    outcome: str = "paid"  # paid | failed


@router.post("/api/simulate/payment")
def simulate_payment(body: SimulateIn, db: Session = Depends(get_db)):
    """Local-dev stand-in for the Razorpay webhook (no public URL on localhost).
    Same code path as the real webhook handler."""
    link = db.query(PaymentLink).filter_by(razorpay_link_id=body.razorpay_link_id).first()
    if not link:
        raise HTTPException(404, "payment link not found")
    return _mark_link(db, link, body.outcome,
                      payment_id=f"pay_simulated_{link.id}" if body.outcome == "paid" else None)
