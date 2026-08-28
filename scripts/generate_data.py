"""Synthetic data generator for RevPulse demo merchant "The Nandana Palace".

Deterministic (fixed seed). Creates ~300 customers, 8 months of orders and
~800 first-party reviews with planted ground-truth patterns P1-P5 plus two
near-miss decoys, then writes the answer key to data/ground_truth.json.

Run:  python scripts/generate_data.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.db import Base, SessionLocal, engine  # noqa: E402
from app import models as m  # noqa: E402

SEED = 42
NOW = datetime(2026, 9, 1)          # fixed reference date -> reproducible
MONTHS = [datetime(2026, mo, 1) for mo in range(1, 9)]  # Jan..Aug 2026
ZONES = ["Indiranagar", "Koramangala", "HSR Layout", "Jayanagar", "Whitefield"]
PACKAGING_ZONE = "Whitefield"       # P4 concentration zone

rng = random.Random(SEED)

# ---------------------------------------------------------------- menu

MENU = [
    ("Hyderabadi Chicken Biryani", "Biryani", 320),
    ("Mutton Dum Biryani", "Biryani", 420),
    ("Veg Biryani", "Biryani", 240),
    ("Egg Biryani", "Biryani", 260),
    ("Prawn Biryani", "Biryani", 450),
    ("Chicken 65", "Starters", 220),
    ("Paneer Tikka", "Starters", 240),
    ("Seekh Kebab", "Starters", 280),
    ("Tandoori Chicken (Half)", "Starters", 300),
    ("Butter Chicken", "Curries", 340),
    ("Paneer Butter Masala", "Curries", 280),
    ("Dal Makhani", "Curries", 220),
    ("Chicken Chettinad", "Curries", 330),
    ("Butter Naan", "Breads", 60),
    ("Garlic Naan", "Breads", 70),
    ("Tandoori Roti", "Breads", 40),
    ("Raita", "Sides", 60),
    ("Gulab Jamun (2 pc)", "Desserts", 90),
    ("Double Ka Meetha", "Desserts", 120),
    ("Masala Buttermilk", "Drinks", 50),
]

FIRST = ["Aarav", "Ananya", "Rohan", "Priya", "Karthik", "Sneha", "Vikram", "Divya",
         "Arjun", "Meera", "Rahul", "Pooja", "Siddharth", "Kavya", "Nikhil", "Shreya",
         "Aditya", "Ishita", "Manish", "Lakshmi", "Varun", "Neha", "Suresh", "Anjali",
         "Kiran", "Deepa", "Harish", "Ritu", "Sanjay", "Tanvi"]
LAST = ["Sharma", "Reddy", "Iyer", "Patel", "Nair", "Gupta", "Rao", "Menon", "Kumar",
        "Joshi", "Shetty", "Verma", "Pillai", "Das", "Kulkarni", "Hegde", "Bhat",
        "Chowdhury", "Srinivasan", "Mehta"]

# ---------------------------------------------------------------- review text pools

SLOW_SERVICE = [  # P1
    "Ordered at {t} and food arrived almost an hour late. Weekend service is painfully slow.",
    "Delivery took forever this {day} evening. Biryani was cold by the time it reached us.",
    "45+ minutes past the promised time. This keeps happening on weekend nights.",
    "Food is good but the wait on {day} night was ridiculous. Almost gave up.",
    "Service has become really slow lately, especially on weekends. Waited over an hour.",
    "Very late delivery again. {day} dinner orders are always delayed from this place.",
]
PACKAGING = [  # P4
    "Gravy spilled all over the bag. Packaging needs serious improvement.",
    "Container lid was open when it arrived, half the raita leaked out.",
    "Biryani box was crushed and leaking. Please fix your packaging.",
    "Second time the packaging failed and the curry spilled in delivery.",
    "Food arrived with the bag soaked in gravy. Poor packaging.",
]
POSITIVE_BIRYANI = [  # P2
    "The {item} was outstanding, perfectly spiced and the meat was so tender.",
    "Best biryani in the area, hands down. {item} is a must-try.",
    "Ordered the {item} for the family, everyone loved it. Authentic dum flavour.",
    "That {item} was incredible. Long grain rice, great aroma, generous portion.",
    "{item} never disappoints. Our weekend ritual at this point.",
    "Absolutely delicious {item}. The saffron aroma alone is worth it.",
]
POSITIVE_OTHER = [
    "The {item} was really good, will order again.",
    "Loved the {item}. Fresh, hot and delivered on time.",
    "{item} was great, portion size is generous for the price.",
    "Solid meal. The {item} stood out. Quick delivery too.",
    "Tried the {item} for the first time, very impressed.",
]
NEGATIVE_MISC = [
    "The {item} was too oily for my taste.",
    "Found the {item} a bit bland today, not up to the usual standard.",
    "Rice was slightly undercooked in my order.",
    "The {item} portion felt smaller than before.",
    "Average experience this time. The {item} was just okay.",
]
NEUTRAL = [
    "Decent food. Nothing exceptional but does the job.",
    "Okay-ish experience. The {item} was fine.",
    "Regular order, standard quality as always.",
]
CHURN_WHALE = [  # P3 — high-LTV churn signals
    "I have been ordering from you every week for months, but the last few orders have been disappointing. Thinking of switching to another place.",
    "Long-time regular here. Quality has dropped noticeably and delivery keeps getting slower. Not sure I will keep ordering.",
    "Used to recommend you to everyone. After the last two bad experiences I am considering other options for our weekly family dinner.",
]
DECOY_PARKING = [  # D1 — tiny, flat trend, should NOT be flagged
    "Pickup parking near the restaurant is difficult on busy roads.",
    "Hard to find parking when collecting the order myself.",
    "Parking around the store is a pain for self-pickup.",
    "No parking space nearby, had to walk a bit for pickup.",
]
DECOY_SPICE = [  # D2 — scattered, no concentration, should NOT be flagged
    "The {item} was a bit too spicy for my kids.",
    "Found the spice level higher than expected.",
    "Could you offer a low-spice option? The {item} was quite hot.",
    "Bit too much chilli in the {item} for my taste.",
    "The {item} was spicier than last time.",
    "Would love a milder version of the {item}.",
]

BIRYANIS = [x[0] for x in MENU if x[1] == "Biryani"]
NON_BIRYANI = [x[0] for x in MENU if x[1] != "Biryani"]


def fill(tpl: str, **kw) -> str:
    if "{item}" in tpl and "item" not in kw:
        kw["item"] = rng.choice(NON_BIRYANI)
    return tpl.format(**kw)


def rand_dt(month: datetime, weekday: int | None = None, hour_range=(11, 22)) -> datetime:
    """Random datetime inside a month; optionally pinned to a weekday."""
    for _ in range(200):
        day = rng.randint(1, 28)
        dt = month.replace(day=day)
        if weekday is not None and dt.weekday() != weekday:
            continue
        return dt.replace(hour=rng.randint(*hour_range), minute=rng.randint(0, 59))
    return month.replace(day=1, hour=hour_range[0])


def make_order(db, cust, ts, want_biryani=False):
    n_items = rng.randint(1, 3)
    picks = []
    if want_biryani:
        picks.append(rng.choice([x for x in MENU if x[1] == "Biryani"]))
        n_items = max(n_items, 2)
    while len(picks) < n_items:
        picks.append(rng.choice(MENU))
    items = [{"item": p[0], "qty": rng.randint(1, 2), "price_inr": p[2]} for p in picks]
    amount = sum(i["qty"] * i["price_inr"] for i in items)
    o = m.Order(customer_id=cust.id, ts=ts, amount_inr=amount,
                items_json=json.dumps(items), zone=cust.zone, status="paid")
    db.add(o)
    db.flush()
    return o


def make_review(db, cust, order, ts, rating, text):
    r = m.Review(customer_id=cust.id, order_id=order.id, ts=ts, rating=rating, text=text)
    db.add(r)
    db.flush()
    return r


def main() -> None:
    db_path = Path(str(engine.url.database))
    if db_path.exists():
        db_path.unlink()
    Base.metadata.create_all(engine)
    db = SessionLocal()

    merchant = m.Merchant(name="The Nandana Palace", city="Bengaluru", category="Restaurant / Delivery")
    db.add(merchant)
    db.flush()
    for name, cat, price in MENU:
        db.add(m.MenuItem(merchant_id=merchant.id, name=name, category=cat, price_inr=price))

    # ---------------- customers (300; 3 whales are P3)
    customers: list[m.Customer] = []
    used_names = set()
    for i in range(300):
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name not in used_names:
                used_names.add(name)
                break
        c = m.Customer(
            merchant_id=merchant.id, name=name,
            email=f"{name.lower().replace(' ', '.')}@example.com",
            phone=f"+91{rng.randint(7000000000, 9999999999)}",
            zone=rng.choice(ZONES),
            first_seen=rand_dt(rng.choice(MONTHS[:4])),
        )
        db.add(c)
        customers.append(c)
    db.flush()

    whales = customers[:3]  # P3: exactly 3 high-LTV churn-risk customers
    regulars = customers[3:120]
    occasionals = customers[120:230]
    one_timers = customers[230:]

    # ---------------- baseline orders
    for c in whales:
        for month in MONTHS[:7]:            # weekly big family orders Jan..Jul
            for _ in range(4):
                make_order(db, c, rand_dt(month, hour_range=(18, 21)), want_biryani=True)
    for c in regulars:
        for month in MONTHS:
            for _ in range(rng.choice([1, 1, 2])):
                if rng.random() < 0.85:
                    make_order(db, c, rand_dt(month), want_biryani=rng.random() < 0.5)
    for c in occasionals:
        for month in MONTHS:
            if rng.random() < 0.4:
                make_order(db, c, rand_dt(month), want_biryani=rng.random() < 0.5)
    for c in one_timers:
        make_order(db, c, rand_dt(rng.choice(MONTHS)), want_biryani=rng.random() < 0.5)

    gt: dict = {}
    review_count = 0

    # ---------------- P1: slow-service cluster, +~30% MoM, Fri/Sat 19-22h (~85 reviews)
    p1_counts = [4, 6, 8, 10, 13, 17, 27]  # Feb..Aug, ~+30-40% MoM, total 85
    p1_ids, p1_customers = [], []
    p1_complaint_ts: dict[int, datetime] = {}
    p1_pool = regulars + occasionals
    rng.shuffle(p1_pool)
    pool_iter = iter(p1_pool)
    for month, count in zip(MONTHS[1:], p1_counts):
        for _ in range(count):
            c = next(pool_iter)
            p1_customers.append(c)
            weekday = rng.choice([4, 5])                    # Fri/Sat
            if rng.random() < 0.12:                         # small noise
                weekday = rng.randint(0, 6)
            ts = rand_dt(month, weekday=weekday, hour_range=(19, 21))
            o = make_order(db, c, ts - timedelta(hours=1))
            day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][ts.weekday()]
            text = fill(rng.choice(SLOW_SERVICE), t=f"{ts.hour}:{ts.minute:02d} PM", day=day)
            r = make_review(db, c, o, ts, rng.choice([1, 2, 2]), text)
            p1_ids.append(r.id)
            p1_complaint_ts[c.id] = ts
            review_count += 1
    gt["P1"] = {
        "pattern": "slow-service complaint cluster",
        "theme": "slow service / late delivery",
        "monthly_counts": dict(zip([mo.strftime("%Y-%m") for mo in MONTHS[1:]], p1_counts)),
        "growth": "~+30-40% month-over-month",
        "time_concentration": "Fri/Sat 7-10 PM",
        "review_ids": p1_ids,
        "expected": "FLAG",
    }

    # ---------------- P5: slow-service reviewers repeat far less (~11% vs baseline)
    # ~11% of complainers order again shortly after; the rest go quiet (their
    # un-reviewed post-complaint baseline orders are pruned at the end).
    p1_repeater_ids: set[int] = set()
    for c in p1_customers:
        if rng.random() < 0.11:
            p1_repeater_ids.add(c.id)
            make_order(db, c, p1_complaint_ts[c.id] + timedelta(days=rng.randint(7, 21)))

    # ---------------- P2: biryani praised in ~70% of positive reviews (~430 positives)
    pos_total = 430
    p2_biryani = int(pos_total * 0.70)
    # P1 complainers are excluded from later review pools so their post-complaint
    # silence (the P5 signal) stays clean.
    p1_id_set = {c.id for c in p1_customers}
    pos_pool = [c for c in regulars + occasionals if c.id not in p1_id_set] + one_timers
    p2_count = 0
    for i in range(pos_total):
        c = rng.choice(pos_pool)
        month = rng.choice(MONTHS)
        ts = rand_dt(month)
        if i < p2_biryani:
            item = rng.choice(BIRYANIS)
            o = make_order(db, c, ts - timedelta(hours=2), want_biryani=True)
            text = fill(rng.choice(POSITIVE_BIRYANI), item=item)
            p2_count += 1
        else:
            o = make_order(db, c, ts - timedelta(hours=2))
            text = fill(rng.choice(POSITIVE_OTHER))
        make_review(db, c, o, ts, rng.choice([4, 5, 5]), text)
        review_count += 1
    gt["P2"] = {
        "pattern": "hero product",
        "product": "biryani",
        "share_of_positive_reviews": round(p2_biryani / pos_total, 2),
        "n_positive": pos_total,
        "expected": "FLAG (promote biryani)",
    }

    # ---------------- P3: the 3 whales post churn-signal reviews (Jul/Aug), then stop
    p3 = []
    for c, tpl in zip(whales, CHURN_WHALE):
        ltv = sum(o.amount_inr for o in db.query(m.Order).filter_by(customer_id=c.id))
        ts = rand_dt(MONTHS[6 + rng.randint(0, 1)], hour_range=(19, 22))
        o = make_order(db, c, ts - timedelta(hours=2), want_biryani=True)
        r = make_review(db, c, o, ts, 2, tpl)
        review_count += 1
        p3.append({"customer_id": c.id, "name": c.name, "ltv_inr": ltv, "review_id": r.id})
    gt["P3"] = {
        "pattern": "high-value churn-risk customers",
        "customers": p3,
        "expected": "FLAG all 3 for recovery offers (LTV > 15000)",
    }

    # ---------------- P4: packaging complaints concentrated in one zone (~35, 80% Whitefield)
    p4_ids = []
    wf = [c for c in pos_pool if c.zone == PACKAGING_ZONE]
    other = [c for c in pos_pool if c.zone != PACKAGING_ZONE]
    for i in range(35):
        c = rng.choice(wf) if i < 28 else rng.choice(other)
        ts = rand_dt(rng.choice(MONTHS[3:]))
        o = make_order(db, c, ts - timedelta(hours=1))
        r = make_review(db, c, o, ts, rng.choice([2, 3]), rng.choice(PACKAGING))
        p4_ids.append(r.id)
        review_count += 1
    gt["P4"] = {
        "pattern": "packaging complaints correlated with delivery zone",
        "zone": PACKAGING_ZONE,
        "zone_share": round(28 / 35, 2),
        "review_ids": p4_ids,
        "expected": "FLAG",
    }

    # ---------------- misc negatives + neutrals (haystack)
    for _ in range(160):
        c = rng.choice(pos_pool)
        ts = rand_dt(rng.choice(MONTHS))
        o = make_order(db, c, ts - timedelta(hours=1))
        make_review(db, c, o, ts, rng.choice([2, 3, 3]), fill(rng.choice(NEGATIVE_MISC)))
        review_count += 1
    for _ in range(60):
        c = rng.choice(pos_pool)
        ts = rand_dt(rng.choice(MONTHS))
        o = make_order(db, c, ts - timedelta(hours=1))
        make_review(db, c, o, ts, 3, fill(rng.choice(NEUTRAL)))
        review_count += 1

    # ---------------- decoys (must NOT be flagged)
    d1_ids = []
    for i in range(4):  # D1 parking: tiny, flat across months
        c = rng.choice(pos_pool)
        ts = rand_dt(MONTHS[i * 2])
        o = make_order(db, c, ts - timedelta(hours=1))
        r = make_review(db, c, o, ts, 3, rng.choice(DECOY_PARKING))
        d1_ids.append(r.id)
        review_count += 1
    d2_ids = []
    for _ in range(8):  # D2 spice: scattered, all zones, all months, flat
        c = rng.choice(pos_pool)
        ts = rand_dt(rng.choice(MONTHS))
        o = make_order(db, c, ts - timedelta(hours=1))
        r = make_review(db, c, o, ts, 3, fill(rng.choice(DECOY_SPICE)))
        d2_ids.append(r.id)
        review_count += 1
    gt["decoys"] = [
        {"name": "parking complaints", "review_ids": d1_ids,
         "reason_not_to_flag": "only 4 reviews, flat trend, no growth, no concentration"},
        {"name": "spice-level comments", "review_ids": d2_ids,
         "reason_not_to_flag": "scattered across months and zones, no trend, mild ratings"},
    ]

    # ---------------- prune complainers' un-reviewed orders after their complaint
    # (this IS the planted P5 signal: they went quiet)
    reviewed_order_ids = {r.order_id for r in db.query(m.Review)}
    for c in p1_customers:
        if c.id in p1_repeater_ids:
            continue
        for o in db.query(m.Order).filter(
            m.Order.customer_id == c.id, m.Order.ts > p1_complaint_ts[c.id]
        ):
            if o.id not in reviewed_order_ids:
                db.delete(o)
    db.commit()

    # ---------------- measure actual P5 stats (repeat = new order within 45d of review)
    slow_cust_ids = p1_id_set
    WINDOW = timedelta(days=45)

    def repeated(c_id: int) -> bool:
        rv = (db.query(m.Review).filter(m.Review.customer_id == c_id)
              .order_by(m.Review.ts.desc()).first())
        return db.query(m.Order).filter(
            m.Order.customer_id == c_id,
            m.Order.ts > rv.ts, m.Order.ts <= rv.ts + WINDOW,
        ).count() > 0

    reviewed_ids = {r.customer_id for r in db.query(m.Review)}
    baseline_ids = [i for i in reviewed_ids if i not in slow_cust_ids]
    slow_rep = sum(repeated(i) for i in slow_cust_ids) / max(len(slow_cust_ids), 1)
    base_rep = sum(repeated(i) for i in baseline_ids) / max(len(baseline_ids), 1)
    gt["P5"] = {
        "pattern": "slow-service reviewers repeat less (association, not causation)",
        "repeat_rate_slow_service": round(slow_rep, 3),
        "repeat_rate_baseline": round(base_rep, 3),
        "n_slow": len(slow_cust_ids),
        "n_baseline": len(baseline_ids),
        "expected": "FLAG as association with sample sizes",
    }

    gt["totals"] = {
        "customers": db.query(m.Customer).count(),
        "orders": db.query(m.Order).count(),
        "reviews": db.query(m.Review).count(),
        "seed": SEED,
        "reference_date": NOW.isoformat(),
    }

    out = Path(__file__).resolve().parent.parent / "data" / "ground_truth.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(gt, indent=2))

    t = gt["totals"]
    print(f"Generated: {t['customers']} customers, {t['orders']} orders, {t['reviews']} reviews")
    print(f"P5 repeat rates: slow={gt['P5']['repeat_rate_slow_service']} baseline={gt['P5']['repeat_rate_baseline']}")
    print(f"Ground truth -> {out}")
    db.close()


if __name__ == "__main__":
    main()
