"""REST surface for the dashboard. Thin wrappers over the tool executors."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import audit
from ..agent import tools
from ..db import get_db
from ..models import Approval, AuditLog, Customer, MenuItem, Merchant, Review

router = APIRouter(prefix="/api")


@router.get("/merchant")
def merchant(db: Session = Depends(get_db)):
    mch = db.query(Merchant).first()
    if not mch:
        raise HTTPException(404, "no merchant seeded")
    return {"id": mch.id, "name": mch.name, "city": mch.city, "category": mch.category,
            "menu": [{"name": i.name, "category": i.category, "price_inr": i.price_inr}
                     for i in db.query(MenuItem).all()]}


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return tools.get_review_stats(db)


@router.get("/reviews")
def reviews(theme: str | None = None, sentiment: str | None = None,
            urgency: str | None = None, churn_signal: bool | None = None,
            month: str | None = None, limit: int = 25, db: Session = Depends(get_db)):
    return tools.get_reviews(db, theme=theme, sentiment=sentiment, urgency=urgency,
                             churn_signal=churn_signal, month=month, limit=limit)


@router.get("/customers")
def customers(min_ltv_inr: int | None = None, churn_signal: bool | None = None,
              zone: str | None = None, inactive_days: int | None = None,
              limit: int = 25, db: Session = Depends(get_db)):
    return tools.get_customers(db, min_ltv_inr=min_ltv_inr, churn_signal=churn_signal,
                               zone=zone, inactive_days=inactive_days, limit=limit)


@router.get("/customers/{customer_id}")
def customer_history(customer_id: int, db: Session = Depends(get_db)):
    return tools.get_customer_history(db, customer_id)


@router.get("/transactions")
def transactions(compare_theme: str | None = None, db: Session = Depends(get_db)):
    return tools.get_transactions(db, compare_theme=compare_theme)


@router.get("/campaigns")
def campaigns(db: Session = Depends(get_db)):
    return tools.get_campaign_results(db)


@router.get("/audit")
def audit_log(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 300)).all()
    return {"entries": [audit.serialize(e) for e in rows]}


@router.get("/approvals")
def approvals(status: str = "pending", db: Session = Depends(get_db)):
    rows = (db.query(Approval).filter(Approval.status == status)
            .order_by(Approval.id.desc()).all())
    return {"approvals": [
        {"id": a.id, "audit_id": a.audit_id, "ts": a.ts.isoformat(), "tool": a.tool,
         "args": json.loads(a.args_json), "agent_reasoning": a.agent_reasoning,
         "status": a.status}
        for a in rows
    ]}


class DraftIn(BaseModel):
    review_id: int
    tone: str = "professional"


@router.post("/reviews/draft-reply")
def draft(body: DraftIn, db: Session = Depends(get_db)):
    r = db.get(Review, body.review_id)
    if not r:
        raise HTTPException(404, "review not found")
    return tools.draft_reply(db, body.review_id, body.tone)
