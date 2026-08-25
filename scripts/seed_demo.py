"""Seed a clean, presentable demo state (run before recording or judging).

Creates one recovery campaign targeting the three planted high-LTV at-risk
customers, then marks two of the three links paid so the dashboard shows real
attributed revenue. Every link is a genuine Razorpay test-mode payment link.

Pair with scripts/reset_demo.py:
    python scripts/reset_demo.py    # clear campaigns/audit, keep reviews
    python scripts/seed_demo.py     # create the demo campaign + redemptions

Note: Razorpay test mode rate-limits bursts of payment-link creation. If you
see "Too many requests" the script has already retried with backoff — wait a
few minutes and run it again.
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

from app import actions, audit, policy  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Customer, PaymentLink  # noqa: E402
from app.routers.actions_api import _mark_link  # noqa: E402
from app.agent import tools  # noqa: E402

REDEEM_COUNT = 2  # how many of the targeted customers "pay" the link

db = SessionLocal()

whales = tools.get_customers(db, min_ltv_inr=15000, churn_signal=True, limit=10)["customers"]
if not whales:
    print("No high-LTV churn-risk customers found — run scripts/generate_data.py and "
          "the extraction pass first.")
    sys.exit(1)

customer_ids = [c["customer_id"] for c in whales[:3]]
print("Targeting high-LTV at-risk customers:")
for c in whales[:3]:
    print(f"  #{c['customer_id']} {c['name']} — LTV ₹{c['ltv_inr']:,}")

args = {"customer_ids": customer_ids, "discount_pct": 15, "expiry_days": 7,
        "reason": "High-LTV customers with churn-signal reviews"}

# Run it through the real path so the audit trail tells the whole story.
verdict, rule = policy.check("create_recovery_offer", args, db)
print(f"\nPolicy verdict: {verdict}" + (f" ({rule})" if rule else ""))
if verdict == policy.BLOCKED:
    print("Blocked — these customers were offered recently. Run scripts/reset_demo.py first.")
    sys.exit(1)

entry = audit.write_ahead(db, actor="agent", tool="create_recovery_offer", args=args,
                          reasoning="Three customers with LTV over ₹15,000 left "
                                    "churn-signal reviews; a bounded win-back offer "
                                    "is the highest-value recovery action available.",
                          verdict=verdict, rule=rule)
try:
    result = actions.execute_action(db, "create_recovery_offer", args)
except Exception as e:
    audit.complete(db, entry, status="failed", error=str(e))
    print(f"\nFailed to create links: {e}")
    print("This is recorded in the audit trail. Wait a few minutes and re-run "
          "(idempotency keys mean a retry cannot double-create).")
    sys.exit(1)

audit.complete(db, entry, status="success",
               razorpay_ref=result["links"][0]["razorpay_link_id"])
print(f"Campaign {result['offer_code']}: {len(result['links'])} real Razorpay test links")
for l in result["links"]:
    print(f"  customer #{l['customer_id']}  ₹{l['amount_inr']}  {l['short_url']}")

paid = 0
for link in db.query(PaymentLink).filter_by(status="created").all():
    if paid >= REDEEM_COUNT:
        break
    res = _mark_link(db, link, "paid", f"pay_demo_{link.id}")
    print(f"  redeemed: customer #{link.customer_id} → ₹{res['amount_inr']} attributed")
    paid += 1

summary = tools.get_campaign_results(db)["campaigns"][0]
print(f"\nDemo state ready — {summary['redeemed']}/{summary['targeted']} redeemed, "
      f"₹{summary['revenue_attributed_inr']:,} attributed, "
      f"₹{summary['incentive_spent_inr']:,} incentive cost, "
      f"net ₹{summary['revenue_attributed_inr'] - summary['incentive_spent_inr']:,}")
db.close()
