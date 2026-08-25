"""Adversarial tests for the policy engine — run BEFORE any real money wiring.

Every case asserts the exact verdict. Exit code != 0 on any failure.

Run:  python scripts/test_policy.py
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import policy  # noqa: E402
from app.db import SessionLocal  # noqa: E402

db = SessionLocal()

CASES = [
    # (name, tool, args, expected_verdict)
    ("read tool auto-allowed", "get_reviews", {"theme": "packaging issue"}, policy.ALLOWED),
    ("draft auto-allowed", "draft_reply", {"review_id": 1, "tone": "friendly"}, policy.ALLOWED),

    # hard money bounds
    ("over-discount blocked", "create_recovery_offer",
     {"customer_ids": [1], "discount_pct": 35, "expiry_days": 7}, policy.BLOCKED),
    ("over-discount campaign blocked", "create_campaign",
     {"segment": "all", "customer_ids": [1, 2], "offer": "x", "discount_pct": 50,
      "budget_inr": 500}, policy.BLOCKED),
    ("over-campaign-cap blocked", "create_campaign",
     {"segment": "all", "customer_ids": [1, 2], "offer": "x", "discount_pct": 10,
      "budget_inr": 3500}, policy.BLOCKED),
    # customer 1 is a whale (AOV ~950): 20% -> ~₹190 estimate -> over ₹150 approval line
    ("whale recovery needs approval", "create_recovery_offer",
     {"customer_ids": [1], "discount_pct": 20, "expiry_days": 7}, policy.NEEDS_APPROVAL),
    # customer 250 is a one-timer (small AOV): 10% -> small value -> auto-allowed
    ("small recovery allowed", "create_recovery_offer",
     {"customer_ids": [250], "discount_pct": 10, "expiry_days": 7}, policy.ALLOWED),

    # approval gates
    ("any campaign needs approval", "create_campaign",
     {"segment": "lapsed", "customer_ids": [1, 2, 3], "offer": "10% off",
      "discount_pct": 10, "budget_inr": 1000}, policy.NEEDS_APPROVAL),
    ("big segment needs approval", "create_recovery_offer",
     {"customer_ids": list(range(1, 40)), "discount_pct": 5, "expiry_days": 7},
     policy.NEEDS_APPROVAL),
    ("public reply needs approval", "post_reply",
     {"review_id": 1, "text": "Thanks!"}, policy.NEEDS_APPROVAL),

    # forbidden actions (tools that do not even exist)
    ("refund always blocked", "create_refund", {"payment_id": "pay_x"}, policy.BLOCKED),
    ("payout change always blocked", "update_payout", {"account": "x"}, policy.BLOCKED),
    ("unknown tool blocked", "transfer_funds", {"to": "x"}, policy.BLOCKED),

    # invalid input
    ("zero-amount link blocked", "create_payment_link",
     {"customer_id": 1, "amount_inr": 0}, policy.BLOCKED),
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

# whale at max legal discount 20% with AOV > 1500 would exceed the ₹300 value cap;
# our whales are ~950 AOV so the value cap is exercised via the estimate directly.
big = policy.est_offer_value_inr({"customer_ids": [1], "discount_pct": 20}, db)
ok = 150 < big <= 300
failed += not ok
print(f"[{'PASS' if ok else 'FAIL'}] whale est value ₹{big} sits in approval band (150,300]")

db.close()
print(f"\n{len(CASES) + 1 - failed}/{len(CASES) + 1} passed")
sys.exit(1 if failed else 0)
