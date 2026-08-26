"""Bring order volume up to what a real delivery restaurant actually takes.

The original generator was built for review intelligence: ~300 customers who all
leave feedback. That produced about ten orders a day, which is not a restaurant
— and demand forecasting has nothing to work with at that volume.

This script adds the rest of the business: online orders from walk-in customers
who never leave a review, at a realistic hourly and weekly shape, with the
Friday and Saturday evening rush that the planted service complaints already
cluster in.

Deliberately additive and separate:
  - new customers only, so existing lifetime values, the planted high-value
    churn cohort and every threshold that scores against them are unchanged
  - no reviews, so the cached extraction is untouched and costs nothing to redo
  - seeded, so it produces the same business twice

Run once:  python scripts/add_order_volume.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from generate_data import FIRST, LAST, MENU, MONTHS, ZONES  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Customer, Order  # noqa: E402

SEED = 4242
TAG = "Walk-in"
N_CUSTOMERS = 600
BASE_ORDERS_PER_DAY = 46          # before the day-of-week shape is applied

# A restaurant's week: quiet start, heavy weekend.
DOW_WEIGHT = {0: 0.85, 1: 0.80, 2: 0.85, 3: 0.95, 4: 1.40, 5: 1.35, 6: 1.15}

# Lunch and dinner peaks across trading hours.
HOUR_WEIGHT = {11: 0.5, 12: 1.5, 13: 1.4, 14: 0.8, 15: 0.5, 16: 0.6,
               17: 0.8, 18: 1.2, 19: 2.0, 20: 1.9, 21: 1.1, 22: 0.5}

# The Friday/Saturday evening rush — the same window where the planted
# slow-service complaints concentrate.
RUSH_DAYS = {4, 5}
RUSH_HOURS = {19, 20}
RUSH_MULTIPLIER = 1.8

BIRYANI_BIAS = 0.55               # this is a biryani house, after all

rng = random.Random(SEED)
db = SessionLocal()

if db.query(Customer).filter(Customer.name.like(f"{TAG}%")).count():
    print("Walk-in volume already added — nothing to do.")
    raise SystemExit

biryanis = [m for m in MENU if m[1] == "Biryani"]
others = [m for m in MENU if m[1] != "Biryani"]

# ---------------------------------------------------------------- customers
customers: list[Customer] = []
for i in range(N_CUSTOMERS):
    name = f"{TAG} {rng.choice(FIRST)} {rng.choice(LAST)} {i}"
    c = Customer(merchant_id=1, name=name,
                 email=f"walkin{i}@example.com",
                 phone=f"+91{rng.randint(7000000000, 9999999999)}",
                 zone=rng.choice(ZONES),
                 first_seen=MONTHS[0])
    db.add(c)
    customers.append(c)
db.flush()
print(f"added {len(customers)} walk-in customers")

# ---------------------------------------------------------------- orders
start = MONTHS[0]
end = MONTHS[-1] + timedelta(days=27)
hours, weights = zip(*HOUR_WEIGHT.items())

created = 0
day = start
while day <= end:
    n = BASE_ORDERS_PER_DAY * DOW_WEIGHT[day.weekday()]
    n = max(1, int(round(rng.gauss(n, n * 0.12))))

    hour_weights = [
        w * (RUSH_MULTIPLIER if day.weekday() in RUSH_DAYS and h in RUSH_HOURS else 1.0)
        for h, w in zip(hours, weights)
    ]
    for hour in rng.choices(hours, weights=hour_weights, k=n):
        cust = rng.choice(customers)
        picks = [rng.choice(biryanis if rng.random() < BIRYANI_BIAS else others)]
        for _ in range(rng.randint(0, 2)):
            picks.append(rng.choice(MENU))
        items = [{"item": p[0], "qty": 1, "price_inr": p[2]} for p in picks]
        db.add(Order(
            customer_id=cust.id,
            ts=day.replace(hour=hour, minute=rng.randint(0, 59)),
            amount_inr=sum(i["qty"] * i["price_inr"] for i in items),
            items_json=json.dumps(items),
            zone=cust.zone,
            status="paid",
        ))
        created += 1
    if created % 2000 < n:
        db.flush()
    day += timedelta(days=1)

db.commit()

total = db.query(Order).count()
days = len({o.ts.date() for o in db.query(Order.ts).all()} or {1})
print(f"added {created:,} orders — {total:,} total, about {total // max(days, 1)} a day")

grid: Counter = Counter()
for (ts,) in db.query(Order.ts).all():
    grid[(ts.weekday(), (ts.hour // 2) * 2)] += 1
names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
print("\norders by day and window")
print("     " + "".join(f"{h:02d}-{h + 2:02d}".rjust(7) for h in range(10, 24, 2)))
for d in range(7):
    print(f"{names[d]}  " + "".join(f"{grid[(d, h)]:>6} " for h in range(10, 24, 2)))
db.close()
