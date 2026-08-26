"""Demand planning: one forecast, one plan, one outcome.

No approvals, no policy gate, no Razorpay: this capability spends no money, so
it needs no financial guardrails. It still writes to the audit trail, because
the merchant should be able to see everything the agent did, money or not.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import audit, demand, policy
from ..db import get_db
from ..models import DemandPlan

router = APIRouter(prefix="/api/demand")


def _serialize(plan: DemandPlan, db) -> dict:
    return {
        "id": plan.id,
        "created_ts": plan.ts.isoformat() + "Z",
        "target_date": plan.target_date,
        "day_name": plan.day_name,
        "window_label": plan.window_label,
        "expected_orders": plan.expected_orders,
        "baseline_orders": plan.baseline_orders,
        "uplift_pct": plan.uplift_pct,
        "confidence": plan.confidence,
        "drivers": json.loads(plan.drivers_json),
        "checklist": json.loads(plan.checklist_json),
        "recommendation": plan.recommendation,
        "status": plan.status,
        "outcome": demand.measure_plan(db, plan),
    }


@router.get("/forecast")
def get_forecast(db: Session = Depends(get_db)):
    """What is coming, what will drive it, why we think so, what to prepare."""
    data = demand.forecast(db)
    plans = (db.query(DemandPlan).order_by(DemandPlan.id.desc()).limit(5).all())
    return {
        "forecast": data,
        "reason": None if data else (
            "No window is reliably busier than a normal day yet. A pattern needs at "
            f"least {demand.MIN_OBSERVATIONS} comparable occurrences before it is worth "
            "preparing for."
        ),
        "plans": [_serialize(p, db) for p in plans],
    }


@router.post("/plan")
def create_plan(db: Session = Depends(get_db)):
    """Turn the current forecast into an operational preparation plan."""
    data = demand.forecast(db)
    if not data:
        raise HTTPException(409, "no demand spike to prepare for")
    peak = data["peak"]

    existing = (db.query(DemandPlan)
                .filter_by(target_date=peak["target_date"], window_start=peak["window_start"])
                .first())
    if existing:
        return {"created": False, "plan": _serialize(existing, db),
                "note": "A plan already exists for this window."}

    entry = audit.write_ahead(
        db, actor="merchant", tool="create_preparation_plan",
        args={"target_date": peak["target_date"], "window": peak["window_label"],
              "expected_orders": peak["expected_orders"]},
        reasoning=data["recommendation"],
        verdict=policy.ALLOWED, rule="operational-action: prepares capacity, spends nothing",
    )
    plan = DemandPlan(
        target_date=peak["target_date"], day_name=peak["day_name"],
        window_start=peak["window_start"], window_label=peak["window_label"],
        expected_orders=peak["expected_orders"], baseline_orders=peak["baseline_orders"],
        uplift_pct=peak["uplift_pct"], confidence=peak["confidence"],
        drivers_json=json.dumps(data["drivers"]),
        checklist_json=json.dumps(data["checklist"]),
        recommendation=data["recommendation"],
    )
    db.add(plan)
    db.commit()
    audit.complete(db, entry, status="success")
    return {"created": True, "plan": _serialize(plan, db)}
