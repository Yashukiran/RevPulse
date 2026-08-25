"""Reset demo state: clears campaigns, payment links, approvals, audit log,
budget spend, offer redemptions, and attributed orders — WITHOUT touching
reviews or their cached extraction (so no re-extraction cost).

Run before recording the demo video for a clean slate:
  python scripts/reset_demo.py
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Approval, AuditLog, BudgetSpend, Campaign, OfferRedemption, Order, PaymentLink,
)

db = SessionLocal()
n_orders = db.query(Order).filter(Order.campaign_id.isnot(None)).delete()
for model in (PaymentLink, OfferRedemption, Approval, AuditLog, BudgetSpend, Campaign):
    n = db.query(model).delete()
    print(f"cleared {model.__tablename__}: {n}")
print(f"cleared attributed orders: {n_orders}")
db.commit()
db.close()
print("demo state reset — reviews and extraction preserved")
