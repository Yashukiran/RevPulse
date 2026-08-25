"""End-to-end proof of the autonomous money loop.

    scan -> churn-risk opportunity (evidence + money maths + policy verdict)
         -> merchant approval
         -> real Razorpay test-mode payment links with a unique offer code
         -> payment webhook
         -> revenue attributed back to the opportunity
         -> complete audit trail

Hermetic: creates its own at-risk fixture customer, and removes everything it
made, so it can be run repeatedly without touching demo state or burning the
Razorpay test-mode payment-link quota beyond one link per run.

Run:  python scripts/test_agent_loop.py
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

import policy_fixtures as fx  # noqa: E402
from app import opportunities as opps  # noqa: E402
from app import policy  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog, BudgetSpend, Campaign, Customer, OfferRedemption, Opportunity,
    Order, PaymentLink, Review,
)
from app.routers.actions_api import _mark_link  # noqa: E402
from app.routers.opportunities_api import approve_opportunity  # noqa: E402

db = SessionLocal()
fails = 0
TAG = "__loop_fixture__"


def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def cleanup():
    """Remove everything this run created."""
    cust = db.query(Customer).filter(Customer.name.like(f"{TAG}%")).all()
    ids = [c.id for c in cust]
    if ids:
        for opp in db.query(Opportunity).all():
            if set(json.loads(opp.customer_ids_json)) & set(ids):
                if opp.campaign_id:
                    db.query(PaymentLink).filter_by(campaign_id=opp.campaign_id).delete(
                        synchronize_session=False)
                    db.query(OfferRedemption).filter_by(campaign_id=opp.campaign_id).delete(
                        synchronize_session=False)
                    db.query(BudgetSpend).filter_by(campaign_id=opp.campaign_id).delete(
                        synchronize_session=False)
                    db.query(Order).filter_by(campaign_id=opp.campaign_id).delete(
                        synchronize_session=False)
                    db.query(Campaign).filter_by(id=opp.campaign_id).delete(
                        synchronize_session=False)
                db.delete(opp)
        db.query(Review).filter(Review.customer_id.in_(ids)).delete(synchronize_session=False)
        db.query(OfferRedemption).filter(OfferRedemption.customer_id.in_(ids)).delete(
            synchronize_session=False)
        db.query(Order).filter(Order.customer_id.in_(ids)).delete(synchronize_session=False)
        db.query(Customer).filter(Customer.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    fx.cleanup(db)


cleanup()

# ---------------------------------------------------------------- fixture
# A high-value customer who just told us they are leaving.
cust = Customer(merchant_id=1, name=f"{TAG} Ravi Kumar", email="ravi@fixture.invalid",
                phone="+910000000001", zone="Indiranagar", first_seen=datetime.utcnow())
db.add(cust)
db.flush()
for _ in range(20):   # LTV 20 x 900 = ₹18,000 -> above the ₹15,000 high-value line
    db.add(Order(customer_id=cust.id, ts=datetime.utcnow() - timedelta(days=60),
                 amount_inr=900, items_json="[]", zone=cust.zone, status="paid"))
order = Order(customer_id=cust.id, ts=datetime.utcnow() - timedelta(days=10),
              amount_inr=900, items_json="[]", zone=cust.zone, status="paid")
db.add(order)
db.flush()
db.add(Review(customer_id=cust.id, order_id=order.id, ts=datetime.utcnow() - timedelta(days=9),
              rating=2, text="Been ordering weekly for months but the last few were bad. "
                             "Probably switching to another place.",
              sentiment="negative", themes_json=json.dumps(["food quality issue"]),
              urgency="urgent", churn_signal=True))
db.commit()
print(f"fixture: {cust.name} (id {cust.id}), LTV ₹18,900, churn-signal review\n")

audit_before = db.query(AuditLog).count()

# ---------------------------------------------------------------- 1. detection
found = opps.scan(db)
check("agent finds opportunities unprompted", len(found) >= 1,
      f"({len(found)}: {[o.kind for o in found]})")

# A scan can raise several opportunities from different signals; take the one
# that picked up this fixture customer's churn-signal review.
opp = next((o for o in found
            if cust.id in json.loads(o.customer_ids_json)), None)
check("the churn signal reached a proposal", opp is not None)
data = opps.serialize(opp, db)
check("targets the at-risk customer", cust.id in data["customer_ids"],
      f"({len(data['customer_ids'])} targeted)")

# ---------------------------------------------------------------- 2. evidence & maths
ev = data["evidence"]
check("evidence carries the customer's own words",
      any("switching" in c["review"]["text"] for c in ev["customers"]))
check("revenue at risk is real LTV", data["revenue_at_risk_inr"] >= 18000,
      f"(₹{data['revenue_at_risk_inr']:,})")
check("maximum exposure is bounded and stated",
      0 < data["max_exposure_inr"] <= policy.MAX_RECOVERY_VALUE_INR * len(data["customer_ids"]),
      f"(₹{data['max_exposure_inr']:,})")
check("projection labels its assumption", "assumption" in ev["assumption_note"].lower())
print(f"       at risk ₹{data['revenue_at_risk_inr']:,} | expected ₹{data['expected_revenue_inr']:,}"
      f" | max exposure ₹{data['max_exposure_inr']:,}")
print(f"       rationale: {data['rationale'][:150]}...")

# ---------------------------------------------------------------- 3. guardrails
check("policy evaluated before the merchant sees it",
      data["policy_verdict"] in {policy.ALLOWED, policy.NEEDS_APPROVAL},
      f"({data['policy_verdict']}: {data['policy_rule_hit']})")

# ---------------------------------------------------------------- 4. approval -> execution
res = approve_opportunity(opp.id, db)
check("merchant approval executes the action", res.get("executed") is True,
      f"({res.get('error') or res.get('rule') or 'ok'})")
db.refresh(opp)
check("opportunity is now executed", opp.status == "executed", f"({opp.status})")

links = db.query(PaymentLink).filter_by(campaign_id=opp.campaign_id).all()
check("real Razorpay objects created",
      bool(links) and all(l.razorpay_link_id.startswith(("plink_", "order_")) for l in links),
      f"({links[0].short_url or links[0].razorpay_link_id if links else 'none'})")
camp = db.get(Campaign, opp.campaign_id)
check("campaign carries a unique offer code", bool(camp and camp.offer_code))

# ---------------------------------------------------------------- 5. payment -> attribution
link = links[0]
_mark_link(db, link, "paid", f"pay_loop_{link.id}")
out = opps.measured(db, opp)
check("payment attributed back to the opportunity",
      out["redeemed"] == 1 and out["revenue_inr"] == link.amount_inr,
      f"(₹{out['revenue_inr']:,} from {out['redeemed']}/{out['targeted']})")
attributed_order = (db.query(Order).filter_by(campaign_id=opp.campaign_id)
                    .order_by(Order.id.desc()).first())
check("attributed order written with campaign id", attributed_order is not None)

# webhook replay must not double-count
_mark_link(db, link, "paid", f"pay_loop_{link.id}")
check("webhook replay does not double-attribute",
      db.query(Order).filter_by(campaign_id=opp.campaign_id).count() == 1)

# ---------------------------------------------------------------- 6. audit trail
trail = (db.query(AuditLog).filter(AuditLog.id > audit_before)
         .order_by(AuditLog.id).all())
tools = [e.tool for e in trail]
check("scan is audited", "scan_opportunities" in tools)
check("money action is audited", "create_recovery_offer" in tools)
check("payment webhook is audited", any(t.startswith("webhook:payment") for t in tools))
check("every audited action carries a verdict", all(e.policy_verdict for e in trail))
check("write-ahead: nothing left pending", all(e.status != "pending" for e in trail))

print("\naudit trail for this loop:")
for e in trail:
    print(f"  #{e.id} {e.actor:<9} {e.tool:<26} {e.policy_verdict:<15} {e.status:<10}"
          f" {(e.policy_rule_hit or '')[:52]}")

net = out["revenue_inr"] - out["incentive_inr"]
print(f"\nOutcome: {out['redeemed']}/{out['targeted']} redeemed · "
      f"₹{out['revenue_inr']:,} attributed · ₹{out['incentive_inr']:,} incentive · "
      f"net ₹{net:,}")

cleanup()
db.close()
print(f"\n{'LOOP COMPLETE — ALL PASS' if not fails else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
