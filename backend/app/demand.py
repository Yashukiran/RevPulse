"""Demand planning: predict the next busy window and what to prepare for.

Deliberately different from the win-back agent. That one recovers customers by
spending money; this one protects revenue by preparing operations. It creates no
offers, no payment links and no Razorpay objects — the output is a preparation
plan, not a transaction.

Every number here is computed from the merchant's own order history in plain
Python. No model is asked to forecast anything; the model is used once, at the
end, to turn the finished numbers into a sentence a restaurant owner would say
out loud.

    observe history → detect the recurring pattern → forecast the next occurrence
    → identify what will sell → check service pressure → recommend preparation
    → measure forecast against actual
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from . import aggregates
from .models import Order, Review

# Two-hour service windows. Kept coarse on purpose: a kitchen prepares for
# "Friday evening", not for 18:47.
WINDOW_HOURS = 2
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

MIN_OBSERVATIONS = 6      # below this there is no pattern, only noise
RECENT_WINDOW = 8         # comparable occurrences used for the forecast
CONSISTENCY_WINDOW = 14   # how far back the "12 of the last 14" evidence looks
MIN_UPLIFT = 0.15         # a spike worth preparing for, not ordinary variation

EXPLAIN_MODEL = "claude-haiku-4-5-20251001"

# One model call per distinct forecast, cached for the life of the process.
_recommendation_cache: dict[str, str] = {}


def _window_start(hour: int) -> int:
    return (hour // WINDOW_HOURS) * WINDOW_HOURS


def _window_label(start: int) -> str:
    def fmt(h: int) -> str:
        suffix = "AM" if h < 12 else "PM"
        hour12 = h % 12 or 12
        return f"{hour12} {suffix}"
    return f"{fmt(start)}–{fmt((start + WINDOW_HOURS) % 24)}"


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def _slot_history(db) -> tuple[dict, dict]:
    """Order counts per dated occurrence of each (weekday, window) slot.

    Returns (per_slot_occurrences, per_window_occurrences) where each value maps
    to {date: order_count}. The second is the "a normal day in this window"
    baseline, taken across every weekday.
    """
    agg = aggregates.build(db)
    return agg.slot_dates, agg.window_dates


def _next_occurrence(weekday: int, window_start: int, today: date) -> date:
    """The next calendar date this slot comes round."""
    ahead = (weekday - today.weekday()) % 7
    if ahead == 0:
        ahead = 7   # today's window may already have passed; plan for the next one
    return today + timedelta(days=ahead)


def _confidence(observations: int, consistency: float) -> str:
    if observations >= 12 and consistency >= 0.75:
        return "High"
    if observations >= MIN_OBSERVATIONS and consistency >= 0.6:
        return "Medium"
    return "Low"


def detect_peak(db, today: date | None = None,
                slot_history: tuple | None = None) -> dict | None:
    """Find the upcoming window where demand reliably runs above a normal day."""
    today = today or datetime.utcnow().date()
    per_slot, per_window = slot_history if slot_history else _slot_history(db)
    if not per_slot:
        return None

    baseline_by_window = {
        start: _median(list(counts.values())) for start, counts in per_window.items()
    }

    best = None
    for (weekday, start), counts in per_slot.items():
        dated = sorted(counts.items())
        if len(dated) < MIN_OBSERVATIONS:
            continue
        values = [c for _, c in dated]
        baseline = baseline_by_window.get(start, 0)
        if baseline <= 0:
            continue

        recent = values[-RECENT_WINDOW:]
        expected = _median(recent)
        uplift = (expected - baseline) / baseline
        if uplift < MIN_UPLIFT:
            continue

        window = values[-CONSISTENCY_WINDOW:]
        above = sum(1 for v in window if v > baseline)
        consistency = above / len(window)

        candidate = {
            "weekday": weekday,
            "day_name": DAY_NAMES[weekday],
            "window_start": start,
            "window_label": _window_label(start),
            "expected_orders": int(round(expected)),
            "baseline_orders": int(round(baseline)),
            "uplift_pct": round(uplift * 100, 1),
            "observations": len(values),
            "comparable_above": above,
            "comparable_total": len(window),
            "consistency": round(consistency, 2),
            "confidence": _confidence(len(values), consistency),
            "recent_counts": values[-CONSISTENCY_WINDOW:],
            "trend_up": len(values) >= 4 and _median(values[-4:]) > _median(values[:-4] or values),
            "target_date": _next_occurrence(weekday, start, today).isoformat(),
        }
        if best is None or candidate["expected_orders"] - candidate["baseline_orders"] > \
                best["expected_orders"] - best["baseline_orders"]:
            best = candidate
    return best


def product_drivers(db, peak: dict, limit: int = 5) -> dict:
    """What actually sells in that window, and how much more of it than usual.

    Both figures are rounded to whole dishes BEFORE the change is worked out, so
    the percentage always matches the two numbers on screen. An owner should be
    able to check the arithmetic in their head; a percentage that does not
    follow from the numbers beside it destroys trust in everything else.
    """
    weekday, start = peak["weekday"], peak["window_start"]
    slot = (weekday, start)

    # All of this comes from the shared single-pass aggregate; the arithmetic
    # below is unchanged, it just no longer re-reads and re-parses every order.
    agg = aggregates.build(db)
    slot_items: Counter = agg.slot_items[slot]
    window_items: Counter = agg.window_items[start]
    slot_dates: set[date] = agg.basket_slot_days[slot]
    window_dates: set[date] = agg.basket_window_days[start]
    slot_orders = agg.slot_orders[slot]
    slot_item_count = agg.slot_item_count[slot]
    slot_revenue = agg.slot_revenue[slot]

    if not slot_dates or not window_dates:
        return {"items": [], "items_per_order": 0, "avg_order_value_inr": 0}

    drivers = []
    for item, total in slot_items.most_common(limit * 3):
        expected = round(total / len(slot_dates))
        typical = round(window_items[item] / len(window_dates))
        extra = expected - typical
        if typical < 1 or extra < 1:
            continue
        drivers.append({
            "item": item,
            "typical": typical,
            "expected": expected,
            "extra": extra,
            "change_pct": round((expected - typical) / typical * 100, 1),
        })
    drivers.sort(key=lambda d: -d["extra"])
    return {
        "items": drivers[:limit],
        "items_per_order": round(slot_item_count / slot_orders, 1) if slot_orders else 0,
        "avg_order_value_inr": round(slot_revenue / slot_orders) if slot_orders else 0,
    }


def service_pressure(db, peak: dict) -> dict | None:
    """Whether complaints about speed cluster in this window.

    Reported as an association with both rates and counts. Being busy and having
    complaints at the same time does not prove one caused the other.
    """
    weekday, start = peak["weekday"], peak["window_start"]
    slot_total = slot_slow = other_total = other_slow = 0
    for ts, themes_json in db.query(Review.ts, Review.themes_json).all():
        themes = json.loads(themes_json) if themes_json else []
        slow = "slow delivery/service" in themes
        in_slot = ts.weekday() == weekday and _window_start(ts.hour) == start
        if in_slot:
            slot_total += 1
            slot_slow += slow
        else:
            other_total += 1
            other_slow += slow
    if slot_total < 5 or other_total < 20:
        return None

    slot_rate = slot_slow / slot_total
    other_rate = other_slow / other_total
    if other_rate <= 0 or slot_rate <= other_rate:
        return None
    return {
        "slot_rate": round(slot_rate * 100, 1),
        "other_rate": round(other_rate * 100, 1),
        # Percentage points, because "274% more" reads as a wild claim while
        # "28 in every 100 more reviews" is what actually happened.
        "point_difference": round((slot_rate - other_rate) * 100, 1),
        "slot_n": slot_total,
        "other_n": other_total,
    }


def backtest(db, peak: dict, rounds: int = 4, per_slot: dict | None = None) -> dict | None:
    """Walk forward through history: for each of the last few occurrences,
    forecast it using only what was known before, then compare with what
    happened. Honest accuracy without waiting for the future to arrive.

    `per_slot` lets the caller pass the slot history it already computed, so a
    full forecast reads the order table once instead of twice.
    """
    if per_slot is None:
        per_slot, _ = _slot_history(db)
    dated = sorted(per_slot[(peak["weekday"], peak["window_start"])].items())
    if len(dated) < MIN_OBSERVATIONS + rounds:
        return None

    results = []
    for i in range(len(dated) - rounds, len(dated)):
        prior = [c for _, c in dated[:i]][-RECENT_WINDOW:]
        if len(prior) < 3:
            continue
        forecast = int(round(_median(prior)))
        actual = dated[i][1]
        if actual <= 0:
            continue
        accuracy = max(0.0, 1 - abs(forecast - actual) / actual)
        results.append({"date": dated[i][0].isoformat(), "forecast": forecast,
                        "actual": actual, "accuracy_pct": round(accuracy * 100, 1)})
    if not results:
        return None
    return {
        "rounds": results,
        "mean_accuracy_pct": round(sum(r["accuracy_pct"] for r in results) / len(results), 1),
    }


def _recommendation(peak: dict, drivers: list[dict], pressure: dict | None) -> str:
    """One model call, on finished numbers, to say it the way an owner would."""
    extra = peak["expected_orders"] - peak["baseline_orders"]
    top = ", ".join(d["item"] for d in drivers[:3]) or "your usual bestsellers"
    fallback = (
        f"{peak['day_name']} {peak['window_label']} is likely to be your busiest window, "
        f"with around {peak['expected_orders']} orders against a normal {peak['baseline_orders']} "
        f"— roughly {extra} extra orders. Prepare additional {top} ahead of the rush, and make "
        f"sure packaging and delivery capacity are ready before it starts."
    )
    key = json.dumps({"d": peak["day_name"], "w": peak["window_label"],
                      "e": peak["expected_orders"], "b": peak["baseline_orders"],
                      "t": [d["item"] for d in drivers[:3]]}, sort_keys=True)
    if key in _recommendation_cache:
        return _recommendation_cache[key]

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        facts = {
            "day": peak["day_name"],
            "window": peak["window_label"],
            "expected_orders": peak["expected_orders"],
            "normal_orders": peak["baseline_orders"],
            "extra_orders": extra,
            "uplift_pct": peak["uplift_pct"],
            "top_products": [{"item": d["item"], "typical": d["typical"],
                              "expected": d["expected"]} for d in drivers[:3]],
            "slow_service_complaints_higher_by_points": (
                pressure["point_difference"] if pressure else None),
        }
        msg = client.messages.create(
            model=EXPLAIN_MODEL,
            max_tokens=260,
            messages=[{"role": "user", "content": (
                "You advise the owner of Biryani House, a Bengaluru restaurant. These "
                "figures were calculated from their own order history:\n\n"
                f"{json.dumps(facts, indent=2)}\n\n"
                "Write 2-3 short sentences telling the owner what is coming and what to "
                "prepare. Speak plainly, as you would to a restaurant owner — no "
                "statistics vocabulary, no headings, no bullet points. Use ONLY the "
                "numbers given; never invent one. If complaints are higher in this "
                "window, mention preparing early may help avoid delays, but do not claim "
                "it will definitely fix them."
            )}],
        )
        text = msg.content[0].text.strip() or fallback
    except Exception:
        text = fallback
    _recommendation_cache[key] = text
    return text


def preparation_checklist(peak: dict, drivers: list[dict]) -> list[str]:
    """What to get ready. Advice only — nothing here is ordered, booked or
    notified on the owner's behalf, so nothing here says it was."""
    extra = peak["expected_orders"] - peak["baseline_orders"]
    items = [
        f"Prepare about {d['extra']} extra {d['item']}"
        for d in drivers[:3]
    ]
    items.append(f"Keep packaging ready for roughly {extra} additional orders")
    items.append(f"Check kitchen capacity for the {peak['window_label']} window")
    items.append("Check delivery capacity before the rush starts")
    return items[:6]


def forecast(db, today: date | None = None) -> dict | None:
    """The whole Demand Planning page, in one payload."""
    # Read the slot history once and share it with both consumers below.
    history = _slot_history(db)
    peak = detect_peak(db, today, slot_history=history)
    if not peak:
        return None

    driver_data = product_drivers(db, peak)
    drivers = driver_data["items"]
    pressure = service_pressure(db, peak)
    extra_orders = peak["expected_orders"] - peak["baseline_orders"]

    # Said the way an owner would say it — no baselines, no cohorts, no variance.
    evidence = [
        f"We looked at {peak['observations']} similar {peak['day_name']} evenings."
        if peak["window_start"] >= 17 else
        f"We looked at {peak['observations']} similar {peak['day_name']}s.",
        f"{peak['comparable_above']} of the last {peak['comparable_total']} "
        f"{peak['day_name']}s were busier than usual.",
        f"{peak['day_name']} {peak['window_label']} usually gets about "
        f"{peak['expected_orders']} orders, against {peak['baseline_orders']} at "
        f"this time on other days.",
    ]
    if drivers:
        names = " and ".join(d["item"] for d in drivers[:2])
        evidence.append(f"{names} sell the most extra during this time.")

    return {
        "peak": peak,
        "extra_orders": extra_orders,
        "drivers": drivers,
        "items_per_order": driver_data["items_per_order"],
        "revenue_opportunity": {
            "extra_orders": extra_orders,
            "avg_order_value_inr": driver_data["avg_order_value_inr"],
            "potential_inr": extra_orders * driver_data["avg_order_value_inr"],
        },
        "service_pressure": pressure,
        "evidence": evidence,
        "recommendation": _recommendation(peak, drivers, pressure),
        "checklist": preparation_checklist(peak, drivers),
        "accuracy": backtest(db, peak, per_slot=history[0]),
        "method": (
            f"We take the last {RECENT_WINDOW} {peak['day_name']}s in your own order "
            f"history and use the middle value, so one unusually quiet or busy day "
            f"cannot swing the number. The accuracy below is worked out by predicting "
            f"past {peak['day_name']}s using only what was known before each one, then "
            f"checking against what actually happened."
        ),
    }


def measure_plan(db, plan) -> dict:
    """Once the planned window has passed, compare the forecast with what
    happened — orders and dishes both, so the next forecast has something to
    learn from rather than a single number."""
    target = datetime.fromisoformat(plan.target_date).date()         if isinstance(plan.target_date, str) else plan.target_date
    start = datetime.combine(target, datetime.min.time()) + timedelta(hours=plan.window_start)
    end = start + timedelta(hours=WINDOW_HOURS)
    if datetime.utcnow() < end:
        return {"measured": False, "note": "Upcoming"}

    orders = db.query(Order).filter(Order.ts >= start, Order.ts < end).all()
    actual = len(orders)
    if not actual:
        return {"measured": False, "note": "No orders recorded in this window"}

    actual_items: Counter = Counter()
    for o in orders:
        try:
            for it in json.loads(o.items_json):
                actual_items[it["item"]] += it.get("qty", 1)
        except Exception:
            continue

    predicted = json.loads(plan.drivers_json)
    item_results = [{
        "item": d["item"],
        "forecast": d["expected"],
        "actual": actual_items.get(d["item"], 0),
    } for d in predicted]

    return {
        "measured": True,
        "forecast": plan.expected_orders,
        "actual": actual,
        "difference": actual - plan.expected_orders,
        "accuracy_pct": round(max(0.0, 1 - abs(plan.expected_orders - actual) / actual) * 100, 1),
        "items": item_results,
    }
