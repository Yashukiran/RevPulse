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


class SubmitReviewIn(BaseModel):
    name: str = "Guest"
    rating: int
    text: str


@router.post("/reviews/submit")
def submit_review(body: SubmitReviewIn, db: Session = Depends(get_db)):
    """Live first-party feedback: creates the order+review, labels it with the
    extraction model in real time, and pushes it to dashboard subscribers.
    In production this form is linked from the post-payment page, tying every
    review to a real transaction by construction."""
    import json as _json
    import random
    from datetime import datetime

    from ..agent.extraction import extract_one
    from ..models import Order

    if not (1 <= body.rating <= 5) or not body.text.strip():
        raise HTTPException(422, "rating 1-5 and non-empty text required")

    name = body.name.strip() or "Guest"
    cust = db.query(Customer).filter(Customer.name == name).first()
    if not cust:
        cust = Customer(merchant_id=1, name=name,
                        email=f"{name.lower().replace(' ', '.')}@example.com",
                        phone=f"+91{random.randint(7000000000, 9999999999)}",
                        zone="Walk-in", first_seen=datetime.utcnow())
        db.add(cust)
        db.flush()

    order = Order(customer_id=cust.id, ts=datetime.utcnow(), amount_inr=350,
                  items_json=_json.dumps([{"item": "Live order", "qty": 1,
                                           "price_inr": 350}]),
                  zone=cust.zone, status="paid")
    db.add(order)
    db.flush()
    review = Review(customer_id=cust.id, order_id=order.id, ts=datetime.utcnow(),
                    rating=body.rating, text=body.text.strip()[:1000])
    db.add(review)
    db.flush()

    try:
        label = extract_one(review)
    except Exception:
        label = None  # extraction failure must not lose the review
    if label:
        review.sentiment = label.get("sentiment")
        review.themes_json = _json.dumps(label.get("themes", []))
        review.urgency = label.get("urgency")
        review.churn_signal = bool(label.get("churn_signal"))
    db.commit()

    payload = {
        "id": review.id, "ts": review.ts.isoformat(), "rating": review.rating,
        "text": review.text, "customer": cust.name,
        "sentiment": review.sentiment, "themes": _json.loads(review.themes_json or "[]"),
        "urgency": review.urgency, "churn_signal": review.churn_signal,
    }
    audit.broadcast_review(payload)
    return payload


class DraftIn(BaseModel):
    review_id: int
    tone: str = "professional"


@router.post("/reviews/draft-reply")
def draft(body: DraftIn, db: Session = Depends(get_db)):
    r = db.get(Review, body.review_id)
    if not r:
        raise HTTPException(404, "review not found")
    return tools.draft_reply(db, body.review_id, body.tone)
