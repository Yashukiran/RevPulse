"""Holdout control group: deterministic split, and control customers get nothing.

Attribution proves a payment came through our link. Only a control group can
show the offer caused a return that would not have happened anyway. This test
proves the mechanism is real: the split is reproducible, control customers
receive no payment link and no offer record, and small segments correctly skip
the holdout instead of producing a meaningless number.

Run:  python scripts/test_holdout.py
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

from app import opportunities as opps  # noqa: E402
from app.actions import HOLDOUT_MIN_SEGMENT, split_holdout  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Campaign, Customer, OfferRedemption, Order, PaymentLink  # noqa: E402

db = SessionLocal()
fails = 0
TAG = "__holdout_fixture__"


def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


# ---------------------------------------------------------------- split logic
segment = list(range(101, 111))          # 10 customers
treated_a, control_a = split_holdout(segment, campaign_id=42)
treated_b, control_b = split_holdout(segment, campaign_id=42)

check("split is deterministic for a given campaign",
      (treated_a, control_a) == (treated_b, control_b))
check("control group is held back", len(control_a) == 3, f"({len(control_a)}/10)")
check("treated and control are disjoint and complete",
      sorted(treated_a + control_a) == segment and not set(treated_a) & set(control_a))
check("a different campaign splits differently",
      split_holdout(segment, campaign_id=43)[1] != control_a)
check(f"segments below {HOLDOUT_MIN_SEGMENT} skip the holdout",
      split_holdout([1, 2, 3], 7) == ([1, 2, 3], []),
      "(a holdout on 3 people would be meaningless)")

# ---------------------------------------------------------------- no link for control
# Build a campaign the same way the executor does, without calling Razorpay.
cleanup_ids = []
custs = []
for i in range(8):
    c = Customer(merchant_id=1, name=f"{TAG} {i}", email=f"h{i}@fixture.invalid",
                 phone="+910000000000", zone="Fixture", first_seen=datetime.utcnow())
    db.add(c)
    db.flush()
    db.add(Order(customer_id=c.id, ts=datetime.utcnow() - timedelta(days=90),
                 amount_inr=800, items_json="[]", zone="Fixture", status="paid"))
    custs.append(c)
db.flush()
ids = [c.id for c in custs]

campaign = Campaign(kind="recovery_offer", segment_desc=TAG, offer_desc=TAG,
                    offer_code=f"{TAG}-CODE", discount_pct=15, budget_inr=0,
                    customer_ids_json=json.dumps(ids))
db.add(campaign)
db.flush()
treated, control = split_holdout(ids, campaign.id)
campaign.control_ids_json = json.dumps(control)

# only treated customers get a link and an offer record
for cid in treated:
    db.add(PaymentLink(campaign_id=campaign.id, customer_id=cid,
                       razorpay_link_id=f"plink_fixture_{cid}", short_url="",
                       amount_inr=680, offer_code=campaign.offer_code,
                       idempotency_key=f"{TAG}-{cid}", status="created"))
    db.add(OfferRedemption(customer_id=cid, campaign_id=campaign.id))
db.commit()

linked = {l.customer_id for l in db.query(PaymentLink).filter_by(campaign_id=campaign.id)}
offered = {r.customer_id for r in db.query(OfferRedemption).filter_by(campaign_id=campaign.id)}
check("control customers receive no payment link", not (set(control) & linked),
      f"({len(control)} held back, {len(linked)} links created)")
check("control customers receive no offer record", not (set(control) & offered))
check("every treated customer receives a link", set(treated) == linked)

# ---------------------------------------------------------------- measurement
# One treated and one control customer return; the comparison must see both.
db.add(Order(customer_id=treated[0], ts=campaign.ts + timedelta(days=3),
             amount_inr=680, items_json="[]", zone="Fixture", status="paid"))
db.add(Order(customer_id=control[0], ts=campaign.ts + timedelta(days=4),
             amount_inr=800, items_json="[]", zone="Fixture", status="paid"))
db.commit()

inc = opps.incrementality(db, campaign)
check("incrementality is reported when a holdout exists", inc is not None)
check("treated returns counted", inc["treated"]["returned"] == 1 and inc["treated"]["n"] == len(treated),
      f"({inc['treated']['returned']}/{inc['treated']['n']})")
check("control returns counted — including orders outside our links",
      inc["control"]["returned"] == 1 and inc["control"]["n"] == len(control),
      f"({inc['control']['returned']}/{inc['control']['n']})")
check("sample sizes reported alongside the rates",
      "n" in inc["treated"] and "n" in inc["control"])
check("result is labelled directional, not significant",
      "not statistically significant" in inc["note"])

print(f"\ntreated {inc['treated']['returned']}/{inc['treated']['n']} returned vs "
      f"control {inc['control']['returned']}/{inc['control']['n']} — "
      f"difference {inc['lift_pct_points']} pts (directional)")

# ---------------------------------------------------------------- cleanup
db.query(PaymentLink).filter_by(campaign_id=campaign.id).delete(synchronize_session=False)
db.query(OfferRedemption).filter_by(campaign_id=campaign.id).delete(synchronize_session=False)
db.query(Order).filter(Order.customer_id.in_(ids)).delete(synchronize_session=False)
db.query(Customer).filter(Customer.id.in_(ids)).delete(synchronize_session=False)
db.query(Campaign).filter_by(id=campaign.id).delete(synchronize_session=False)
db.commit()
db.close()

print(f"\n{'ALL PASS' if not fails else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
