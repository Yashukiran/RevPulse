"""Give the demo merchant the order volume of a real, busy restaurant.

The original generator was built for review intelligence: ~300 customers who all
leave feedback, about ten orders a day. That is not a restaurant, and demand
forecasting has nothing to work with at that volume.

This adds the rest of the business — online orders from walk-in customers who
never leave a review — with the shape a restaurant actually has:

  - quiet Mondays, heavy Friday and Saturday evenings
  - lunch and dinner peaks
  - a different menu mix at the weekend dinner rush: more kebabs and mutton
    biryani, because that is what people order on a Friday night

That last point matters. If every window had the same mix, item-level forecasts
would just be the order forecast repeated, and telling the owner "prepare more
of everything" is useless. The rush has its own character, and the forecaster
discovers it rather than being told.

Deliberately additive and separate:
  - new customers only, so existing lifetime values, the planted high-value
    churn cohort and every threshold that scores against them are unchanged
  - no reviews, so the cached extraction is untouched and costs nothing to redo
  - seeded, so it produces the same business twice

Run:  python scripts/add_order_volume.py
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
N_CUSTOMERS = 900
BASE_ORDERS_PER_DAY = 165          # before the day-of-week shape is applied

DOW_WEIGHT = {0: 0.82, 1: 0.78, 2: 0.84, 3: 0.94, 4: 1.42, 5: 1.36, 6: 1.18}

HOUR_WEIGHT = {11: 0.5, 12: 1.6, 13: 1.5, 14: 0.8, 15: 0.5, 16: 0.6,
               17: 0.9, 18: 2.0, 19: 2.4, 20: 2.0, 21: 1.1, 22: 0.5}

# The weekend evening rush — the same window where the planted slow-service
# complaints already concentrate.
RUSH_DAYS = {4, 5}
RUSH_HOURS = {18, 19}
RUSH_MULTIPLIER = 1.7

PRICES = {name: price for name, _cat, price in MENU}
MAINS = [n for n, c, _ in MENU if c in ("Biryani", "Curries")]
STARTERS = [n for n, c, _ in MENU if c == "Starters"]
SIDES = [n for n, c, _ in MENU if c in ("Breads", "Sides", "Desserts", "Drinks")]

# Menu mix by occasion. The rush leans to mutton biryani and kebabs; lunch
# leans to the lighter, cheaper biryanis.
MAIN_WEIGHTS_DEFAULT = {
    "Hyderabadi Chicken Biryani": 5.0, "Mutton Dum Biryani": 3.0, "Veg Biryani": 3.5,
    "Egg Biryani": 2.5, "Prawn Biryani": 1.2, "Butter Chicken": 2.0,
    "Paneer Butter Masala": 1.6, "Dal Makhani": 1.2, "Chicken Chettinad": 1.4,
}
MAIN_WEIGHTS_RUSH = {
    "Hyderabadi Chicken Biryani": 5.5, "Mutton Dum Biryani": 5.5, "Veg Biryani": 2.6,
    "Egg Biryani": 2.0, "Prawn Biryani": 1.8, "Butter Chicken": 2.2,
    "Paneer Butter Masala": 1.3, "Dal Makhani": 0.9, "Chicken Chettinad": 1.6,
}
STARTER_WEIGHTS_DEFAULT = {"Chicken 65": 3.0, "Paneer Tikka": 2.2,
                           "Seekh Kebab": 2.0, "Tandoori Chicken (Half)": 1.8}
STARTER_WEIGHTS_RUSH = {"Chicken 65": 3.2, "Paneer Tikka": 2.0,
                        "Seekh Kebab": 4.6, "Tandoori Chicken (Half)": 2.6}

STARTER_CHANCE_DEFAULT = 0.28
STARTER_CHANCE_RUSH = 0.58

rng = random.Random(SEED)
db = SessionLocal()

# ---------------------------------------------------------------- clean slate
existing = db.query(Customer).filter(Customer.name.like(f"{TAG}%")).all()
if existing:
    ids = [c.id for c in existing]
    removed = db.query(Order).filter(Order.customer_id.in_(ids)).delete(
        synchronize_session=False)
    db.query(Customer).filter(Customer.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    print(f"cleared previous walk-in volume: {removed:,} orders, {len(ids)} customers")

# ---------------------------------------------------------------- customers
customers: list[Customer] = []
for i in range(N_CUSTOMERS):
    name = f"{TAG} {rng.choice(FIRST)} {rng.choice(LAST)} {i}"
    customers.append(Customer(
        merchant_id=1, name=name, email=f"walkin{i}@example.com",
        phone=f"+91{rng.randint(7000000000, 9999999999)}",
        zone=rng.choice(ZONES), first_seen=MONTHS[0],
    ))
db.add_all(customers)
db.flush()
customer_ids = [c.id for c in customers]
print(f"added {len(customers)} walk-in customers")


def pick(weights: dict[str, float]) -> str:
    names = list(weights)
    return rng.choices(names, weights=[weights[n] for n in names], k=1)[0]


def build_order(is_rush: bool) -> list[dict]:
    """One realistic basket: a main, sometimes a starter, usually something else."""
    items = [pick(MAIN_WEIGHTS_RUSH if is_rush else MAIN_WEIGHTS_DEFAULT)]
    if rng.random() < (STARTER_CHANCE_RUSH if is_rush else STARTER_CHANCE_DEFAULT):
        items.append(pick(STARTER_WEIGHTS_RUSH if is_rush else STARTER_WEIGHTS_DEFAULT))
    for _ in range(rng.choices([0, 1, 2], weights=[0.25, 0.5, 0.25], k=1)[0]):
        items.append(rng.choice(SIDES))
    if is_rush and rng.random() < 0.35:      # bigger tables at the weekend rush
        items.append(pick(MAIN_WEIGHTS_RUSH))
    return [{"item": n, "qty": 1, "price_inr": PRICES[n]} for n in items]


# ---------------------------------------------------------------- orders
hours, weights = zip(*HOUR_WEIGHT.items())
rows: list[dict] = []
day = MONTHS[0]
end = MONTHS[-1] + timedelta(days=27)

while day <= end:
    n = BASE_ORDERS_PER_DAY * DOW_WEIGHT[day.weekday()]
    n = max(1, int(round(rng.gauss(n, n * 0.10))))
    hour_weights = [
        w * (RUSH_MULTIPLIER if day.weekday() in RUSH_DAYS and h in RUSH_HOURS else 1.0)
        for h, w in zip(hours, weights)
    ]
    for hour in rng.choices(hours, weights=hour_weights, k=n):
        is_rush = day.weekday() in RUSH_DAYS and hour in RUSH_HOURS
        items = build_order(is_rush)
        cid = rng.choice(customer_ids)
        rows.append({
            "customer_id": cid,
            "ts": day.replace(hour=hour, minute=rng.randint(0, 59)),
            "amount_inr": sum(i["price_inr"] for i in items),
            "items_json": json.dumps(items),
            "zone": "",
            "status": "paid",
            "campaign_id": None,
        })
    day += timedelta(days=1)

for i in range(0, len(rows), 5000):
    db.bulk_insert_mappings(Order, rows[i:i + 5000])
db.commit()

total = db.query(Order).count()
days = (end - MONTHS[0]).days + 1
print(f"added {len(rows):,} orders — {total:,} total, about {len(rows) // days} a day")

grid: Counter = Counter()
for (ts,) in db.query(Order.ts).all():
    grid[(ts.weekday(), (ts.hour // 2) * 2)] += 1
names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
print("\norders by day and window")
print("     " + "".join(f"{h:02d}-{h + 2:02d}".rjust(7) for h in range(10, 24, 2)))
for d in range(7):
    print(f"{names[d]}  " + "".join(f"{grid[(d, h)]:>6} " for h in range(10, 24, 2)))
db.close()
