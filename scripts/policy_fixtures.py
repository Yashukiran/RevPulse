"""Hermetic fixtures for policy tests and the evaluation harness.

The policy engine's verdicts depend on real state (how much was spent today,
who was recently offered an offer, who already redeemed). Tests that hard-code
customer ids therefore change their answer as the demo database evolves.

These helpers create throwaway customers with exactly the state each case
needs, and remove them afterwards, so the same script gives the same result on
a fresh clone, mid-demo, or after a reset.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import BudgetSpend, Campaign, Customer, OfferRedemption, Order

FIXTURE_TAG = "__policy_fixture__"


def _mk_customer(db, name: str, order_amounts: list[int]) -> Customer:
    c = Customer(merchant_id=1, name=f"{FIXTURE_TAG} {name}",
                 email=f"{name}@fixture.invalid", phone="+910000000000",
                 zone="Fixture", first_seen=datetime.utcnow())
    db.add(c)
    db.flush()
    for amt in order_amounts:
        db.add(Order(customer_id=c.id, ts=datetime.utcnow() - timedelta(days=30),
                     amount_inr=amt, items_json="[]", zone="Fixture", status="paid"))
    db.flush()
    return c


def create(db) -> dict[str, int]:
    """Create fixture customers. Returns {role: customer_id}."""
    cleanup(db)  # never stack fixtures from an interrupted run

    whale = _mk_customer(db, "whale", [1000, 1000])       # AOV 1000 -> 20% = 200 (approval band)
    small = _mk_customer(db, "small", [300])              # AOV 300  -> 10% = 30  (auto-allowed)
    capped = _mk_customer(db, "capped", [400])            # recently offered -> frequency cap
    redeemed = _mk_customer(db, "redeemed", [400])        # already redeemed -> dedupe

    camp = Campaign(kind="recovery_offer", segment_desc=FIXTURE_TAG,
                    offer_desc=FIXTURE_TAG, offer_code=f"{FIXTURE_TAG}-CODE",
                    discount_pct=10, budget_inr=0, customer_ids_json="[]")
    db.add(camp)
    db.flush()
    db.add(OfferRedemption(customer_id=capped.id, campaign_id=camp.id,
                           sent_ts=datetime.utcnow() - timedelta(days=2)))
    db.add(OfferRedemption(customer_id=redeemed.id, campaign_id=camp.id,
                           sent_ts=datetime.utcnow() - timedelta(days=2),
                           redeemed_ts=datetime.utcnow() - timedelta(days=1)))
    db.commit()

    # A pool of untouched customers for bulk "should be allowed" cases.
    fresh_pool = [c.id for c in db.query(Customer)
                  .filter(~Customer.name.like(f"{FIXTURE_TAG}%"))
                  .order_by(Customer.id.desc()).limit(60).all()]
    blocked = _blocked_ids(db)
    fresh_pool = [cid for cid in fresh_pool if cid not in blocked]

    return {"whale": whale.id, "small": small.id, "capped": capped.id,
            "redeemed": redeemed.id, "campaign": camp.id, "fresh_pool": fresh_pool}


def _blocked_ids(db) -> set[int]:
    from app import policy

    cutoff = datetime.utcnow() - timedelta(days=policy.OFFER_FREQUENCY_DAYS)
    return {r.customer_id for r in db.query(OfferRedemption)
            .filter(OfferRedemption.sent_ts >= cutoff)}


def cleanup(db) -> None:
    """Remove every fixture row so the demo database is left as it was."""
    ids = [c.id for c in db.query(Customer).filter(Customer.name.like(f"{FIXTURE_TAG}%"))]
    camp_ids = [c.id for c in db.query(Campaign).filter(Campaign.segment_desc == FIXTURE_TAG)]
    if ids:
        db.query(OfferRedemption).filter(OfferRedemption.customer_id.in_(ids)).delete(
            synchronize_session=False)
        db.query(Order).filter(Order.customer_id.in_(ids)).delete(synchronize_session=False)
        db.query(Customer).filter(Customer.id.in_(ids)).delete(synchronize_session=False)
    if camp_ids:
        db.query(BudgetSpend).filter(BudgetSpend.campaign_id.in_(camp_ids)).delete(
            synchronize_session=False)
        db.query(Campaign).filter(Campaign.id.in_(camp_ids)).delete(synchronize_session=False)
    db.commit()


def snapshot_todays_budget(db) -> list[dict]:
    """Lift today's spend ledger out of the way so budget-cap cases start from a
    known baseline, returning the rows for restore()."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    rows = db.query(BudgetSpend).filter(BudgetSpend.date == today).all()
    saved = [{"date": r.date, "campaign_id": r.campaign_id,
              "amount_inr": r.amount_inr, "note": r.note} for r in rows]
    for r in rows:
        db.delete(r)
    db.commit()
    return saved


def restore_todays_budget(db, saved: list[dict]) -> None:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    db.query(BudgetSpend).filter(BudgetSpend.date == today).delete(synchronize_session=False)
    for row in saved:
        db.add(BudgetSpend(**row))
    db.commit()


def spend_today(db, amount_inr: int, note: str = FIXTURE_TAG) -> None:
    db.add(BudgetSpend(date=datetime.utcnow().strftime("%Y-%m-%d"),
                       amount_inr=amount_inr, note=note))
    db.commit()
