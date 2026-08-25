"""The agent's proactive loop, end to end.

    scan -> opportunity (evidence + money maths + policy verdict)
         -> merchant approves
         -> Razorpay test-mode payment links with a unique offer code
         -> payment webhook attributes revenue back to the opportunity
         -> every step in the audit trail

Nothing here trusts the model with money: the action was fixed at scan time and
re-checked against the policy engine at the moment of execution.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import actions, audit, opportunities, policy
from ..db import get_db
from ..models import Approval, Campaign, Opportunity

router = APIRouter(prefix="/api/opportunities")


@router.get("")
def list_opportunities(status: str | None = None, limit: int = 20,
                       db: Session = Depends(get_db)):
    q = db.query(Opportunity)
    if status:
        q = q.filter(Opportunity.status == status)
    rows = q.order_by(Opportunity.id.desc()).limit(min(limit, 50)).all()
    return {"opportunities": [opportunities.serialize(o, db) for o in rows]}


@router.post("/scan")
def run_scan(db: Session = Depends(get_db)):
    """Ask the agent to look for opportunities now."""
    found = opportunities.scan(db)
    return {"found": len(found),
            "opportunities": [opportunities.serialize(o, db) for o in found]}


@router.get("/{opportunity_id}")
def get_opportunity(opportunity_id: int, db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opportunity_id)
    if not opp:
        raise HTTPException(404, "opportunity not found")
    return opportunities.serialize(opp, db)


def _execute(db, opp: Opportunity, actor: str, note: str) -> dict:
    """Run the opportunity's proposed action through policy -> audit -> Razorpay."""
    args = json.loads(opp.proposed_args_json)

    # Re-check at execution time: the world may have moved since the scan
    # (budget spent, an offer sent elsewhere). The scan-time verdict is a
    # preview, never an authorisation.
    verdict, rule = policy.check(opp.proposed_tool, args, db)
    entry = audit.write_ahead(db, actor=actor, tool=opp.proposed_tool, args=args,
                              reasoning=f"{note} (opportunity #{opp.id}: {opp.title})",
                              verdict=verdict, rule=rule)
    opp.audit_id = entry.id

    if verdict == policy.BLOCKED:
        audit.complete(db, entry, status="blocked")
        opp.status = "failed"
        opp.policy_verdict = verdict
        opp.policy_rule_hit = rule
        opp.error = f"Blocked at execution: {rule}"
        db.commit()
        audit.broadcast_opportunity(opportunities.serialize(opp, db))
        return {"executed": False, "verdict": verdict, "rule": rule}

    try:
        result = actions.execute_action(db, opp.proposed_tool, args)
        campaign = (db.query(Campaign).filter_by(offer_code=result.get("offer_code")).first()
                    if result.get("offer_code") else None)
        opp.campaign_id = campaign.id if campaign else None
        opp.status = "executed"
        opp.policy_verdict = policy.ALLOWED
        opp.decided_ts = datetime.utcnow()
        ref = (result.get("links") or [{}])[0].get("razorpay_link_id")
        audit.complete(db, entry, status="success", razorpay_ref=ref)
        db.commit()
        audit.broadcast_opportunity(opportunities.serialize(opp, db))
        return {"executed": True, "result": result}
    except Exception as e:
        audit.complete(db, entry, status="failed", error=str(e))
        opp.status = "failed"
        opp.error = str(e)
        db.commit()
        audit.broadcast_opportunity(opportunities.serialize(opp, db))
        # Graceful: the failure is recorded and the action stays safely retryable,
        # because every Razorpay call carries an idempotency key.
        return {"executed": False, "error": str(e),
                "note": "recorded in the audit trail; safe to retry (idempotent)"}


@router.post("/{opportunity_id}/approve")
def approve_opportunity(opportunity_id: int, db: Session = Depends(get_db)):
    """Merchant approves: this is the human gate the whole design exists to serve."""
    opp = db.get(Opportunity, opportunity_id)
    if not opp:
        raise HTTPException(404, "opportunity not found")
    if opp.status in {"executed", "rejected"}:
        raise HTTPException(409, f"opportunity already {opp.status}")

    # If an approval row is already parked for this opportunity, settle it too.
    if opp.approval_id:
        ap = db.get(Approval, opp.approval_id)
        if ap and ap.status == "pending":
            ap.status = "approved"
            ap.decided_ts = datetime.utcnow()
            db.commit()

    return _execute(db, opp, actor="merchant", note="Merchant approved the proposal")


@router.post("/{opportunity_id}/reject")
def reject_opportunity(opportunity_id: int, db: Session = Depends(get_db)):
    opp = db.get(Opportunity, opportunity_id)
    if not opp:
        raise HTTPException(404, "opportunity not found")
    if opp.status == "executed":
        raise HTTPException(409, "opportunity already executed")

    opp.status = "rejected"
    opp.decided_ts = datetime.utcnow()
    if opp.approval_id:
        ap = db.get(Approval, opp.approval_id)
        if ap and ap.status == "pending":
            ap.status = "rejected"
            ap.decided_ts = datetime.utcnow()
    entry = audit.write_ahead(db, actor="merchant", tool=opp.proposed_tool,
                              args=json.loads(opp.proposed_args_json),
                              reasoning=f"Merchant rejected opportunity #{opp.id}",
                              verdict=policy.BLOCKED, rule="merchant-rejected")
    audit.complete(db, entry, status="blocked", error="merchant rejected")
    db.commit()
    audit.broadcast_opportunity(opportunities.serialize(opp, db))
    return {"rejected": True}
