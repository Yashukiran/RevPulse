"""Adversarial tests for the policy engine — run BEFORE any real money wiring.

Hermetic: fixture customers with known state are created and removed, so the
result is identical on a fresh clone, mid-demo, or after a reset.

Run:  python scripts/test_policy.py
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import policy_fixtures as fx  # noqa: E402
from app import policy  # noqa: E402
from app.db import SessionLocal  # noqa: E402

db = SessionLocal()
ids = fx.create(db)
WHALE, SMALL, CAPPED, REDEEMED = ids["whale"], ids["small"], ids["capped"], ids["redeemed"]
FRESH = ids["fresh_pool"]

CASES = [
    # (name, tool, args, expected_verdict)
    ("read tool auto-allowed", "get_reviews", {"theme": "packaging issue"}, policy.ALLOWED),
    ("draft auto-allowed", "draft_reply", {"review_id": 1, "tone": "friendly"}, policy.ALLOWED),

    # hard money bounds
    ("over-discount blocked", "create_recovery_offer",
     {"customer_ids": [SMALL], "discount_pct": 35, "expiry_days": 7}, policy.BLOCKED),
    ("over-discount campaign blocked", "create_campaign",
     {"segment": "all", "customer_ids": [SMALL], "offer": "x", "discount_pct": 50,
      "budget_inr": 500}, policy.BLOCKED),
    ("over-campaign-cap blocked", "create_campaign",
     {"segment": "all", "customer_ids": [SMALL], "offer": "x", "discount_pct": 10,
      "budget_inr": 3500}, policy.BLOCKED),

    # offer-value threshold: AOV 1000 at 20% = est ₹200 -> above the ₹150 line
    ("high-value recovery needs approval", "create_recovery_offer",
     {"customer_ids": [WHALE], "discount_pct": 20, "expiry_days": 7}, policy.NEEDS_APPROVAL),
    # AOV 300 at 10% = est ₹30 -> under the line
    ("small recovery allowed", "create_recovery_offer",
     {"customer_ids": [SMALL], "discount_pct": 10, "expiry_days": 7}, policy.ALLOWED),

    # approval gates
    ("any campaign needs approval", "create_campaign",
     {"segment": "lapsed", "customer_ids": [SMALL], "offer": "10% off",
      "discount_pct": 10, "budget_inr": 1000}, policy.NEEDS_APPROVAL),
    ("big segment needs approval", "create_recovery_offer",
     {"customer_ids": FRESH[:30], "discount_pct": 5, "expiry_days": 7},
     policy.NEEDS_APPROVAL),
    ("public reply needs approval", "post_reply",
     {"review_id": 1, "text": "Thanks!"}, policy.NEEDS_APPROVAL),

    # customer protection
    ("frequency cap blocks re-target", "create_recovery_offer",
     {"customer_ids": [CAPPED], "discount_pct": 5, "expiry_days": 7}, policy.BLOCKED),
    ("redeemed customer dedupe blocks", "create_recovery_offer",
     {"customer_ids": [REDEEMED], "discount_pct": 5, "expiry_days": 7}, policy.BLOCKED),

    # forbidden actions (tools that do not even exist)
    ("refund always blocked", "create_refund", {"payment_id": "pay_x"}, policy.BLOCKED),
    ("payout change always blocked", "update_payout", {"account": "x"}, policy.BLOCKED),
    ("unknown tool blocked", "transfer_funds", {"to": "x"}, policy.BLOCKED),

    # invalid input
    ("zero-amount link blocked", "create_payment_link",
     {"customer_id": SMALL, "amount_inr": 0}, policy.BLOCKED),
]

failed = 0
for name, tool, args, expected in CASES:
    verdict, rule = policy.check(tool, args, db)
    ok = verdict == expected
    failed += not ok
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: {tool} -> {verdict} ({rule})"
          + ("" if ok else f"  EXPECTED {expected}"))

# pin the estimate helper: fallback AOV 450 at 20% = ₹90
assert policy.est_offer_value_inr({"discount_pct": 20}) == 90
est = policy.est_offer_value_inr({"customer_ids": [WHALE], "discount_pct": 20}, db)
ok = est == 200
failed += not ok
print(f"[{'PASS' if ok else 'FAIL'}] whale est value ₹{est} sits in approval band (150,300]")

fx.cleanup(db)
db.close()
total = len(CASES) + 1
print(f"\n{total - failed}/{total} passed")
sys.exit(1 if failed else 0)
