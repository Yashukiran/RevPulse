"""Phase-4 gate: full money chain against the real Razorpay test-mode API.

policy -> audit -> execute -> real payment link -> (simulated) webhook ->
attribution -> idempotent retry proof. No LLM involved; deterministic.

Run:  python scripts/test_money_chain.py
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

import policy_fixtures as fx  # noqa: E402
from app import actions, audit, policy  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import BudgetSpend, Campaign, OfferRedemption, Order, PaymentLink  # noqa: E402
from app.routers.actions_api import _mark_link  # noqa: E402

db = SessionLocal()
fails = 0

# Hermetic: a fresh fixture customer each run, so the chain (which really does
# create an offer) can be re-run without tripping its own frequency cap.
ids = fx.create(db)
CUSTOMER = ids["small"]
_before_campaign_id = db.query(Campaign.id).order_by(Campaign.id.desc()).first()
_before_campaign_id = _before_campaign_id[0] if _before_campaign_id else 0


def check(name, ok, detail=""):
    global fails
    fails += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


# 1. small recovery offer for a low-AOV customer -> policy ALLOWED
args = {"customer_ids": [CUSTOMER], "discount_pct": 10, "expiry_days": 7,
        "reason": "test chain"}
verdict, rule = policy.check("create_recovery_offer", args, db)
check("policy allows small recovery", verdict == policy.ALLOWED, f"({verdict} {rule})")

entry = audit.write_ahead(db, actor="agent", tool="create_recovery_offer", args=args,
                          reasoning="money-chain test", verdict=verdict, rule=rule)
result = actions.execute_action(db, "create_recovery_offer", args)
audit.complete(db, entry, status="success",
               razorpay_ref=result["links"][0]["razorpay_link_id"])
link_id = result["links"][0]["razorpay_link_id"]
check("real Razorpay link created", link_id.startswith("plink_"),
      f"({result['links'][0]['short_url']})")

# 2. idempotent retry: same args must reuse, not double-create
result2 = actions.execute_action(db, "create_recovery_offer", args)
check("retry reuses existing link (no double-create)",
      result2["links"][0].get("reused") is True
      and result2["links"][0]["razorpay_link_id"] == link_id)
n_links = db.query(PaymentLink).filter_by(razorpay_link_id=link_id).count()
check("exactly one link row in ledger", n_links == 1)

# 3. frequency cap: same customer again within 30 days -> BLOCKED
verdict3, rule3 = policy.check("create_recovery_offer",
                               {"customer_ids": [CUSTOMER], "discount_pct": 5,
                                "expiry_days": 7}, db)
check("frequency cap blocks re-target", verdict3 == policy.BLOCKED, f"({rule3})")

# 4. webhook (simulated locally, same code path as real handler) -> attribution
link_row = db.query(PaymentLink).filter_by(razorpay_link_id=link_id).first()
_mark_link(db, link_row, "paid", "pay_test_chain")
order = (db.query(Order).filter_by(campaign_id=link_row.campaign_id)
         .order_by(Order.id.desc()).first())
check("payment attributed to campaign via order row",
      order is not None and order.amount_inr == link_row.amount_inr)

# 5. webhook retry is idempotent (no second attributed order)
_mark_link(db, link_row, "paid", "pay_test_chain")
n_orders = db.query(Order).filter_by(campaign_id=link_row.campaign_id).count()
check("webhook retry does not double-attribute", n_orders == 1)

# 6. dedupe: customer redeemed -> policy blocks any further offers
verdict6, rule6 = policy.check("create_recovery_offer",
                               {"customer_ids": [CUSTOMER], "discount_pct": 5,
                                "expiry_days": 7}, db)
check("redeemed-customer dedupe blocks", verdict6 == policy.BLOCKED, f"({rule6})")

# 7. campaign results reflect the chain
camp = db.get(Campaign, link_row.campaign_id)
print(f"\ncampaign {camp.offer_code}: targeted 1, redeemed 1, "
      f"revenue ₹{link_row.amount_inr}, incentive ₹{camp.budget_inr}")

# clean up everything this run created, so the demo state is left untouched
_new = [c.id for c in db.query(Campaign).filter(Campaign.id > _before_campaign_id)]
if _new:
    db.query(PaymentLink).filter(PaymentLink.campaign_id.in_(_new)).delete(
        synchronize_session=False)
    db.query(OfferRedemption).filter(OfferRedemption.campaign_id.in_(_new)).delete(
        synchronize_session=False)
    db.query(BudgetSpend).filter(BudgetSpend.campaign_id.in_(_new)).delete(
        synchronize_session=False)
    db.query(Order).filter(Order.campaign_id.in_(_new)).delete(synchronize_session=False)
    db.query(Campaign).filter(Campaign.id.in_(_new)).delete(synchronize_session=False)
    db.commit()
fx.cleanup(db)
db.close()
print(f"\n{'ALL PASS' if not fails else f'{fails} FAILURES'}")
sys.exit(1 if fails else 0)
