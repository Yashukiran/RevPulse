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
    per_slot: dict[tuple[int, int], dict[date, int]] = defaultdict(lambda: defaultdict(int))
    per_window: dict[int, dict[date, int]] = defaultdict(lambda: defaultdict(int))
    for o in db.query(Order).all():
        start = _window_start(o.ts.hour)
        per_slot[(o.ts.weekday(), start)][o.ts.date()] += 1
        per_window[start][o.ts.date()] += 1
    return per_slot, per_window


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


def detect_peak(db, today: date | None = None) -> dict | None:
    """Find the upcoming window where demand reliably runs above a normal day."""
    today = today or datetime.utcnow().date()
    per_slot, per_window = _slot_history(db)
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


def product_drivers(db, peak: dict, limit: int = 5) -> list[dict]:
    """What actually sells in that window, and how much more of it than usual."""
    weekday, start = peak["weekday"], peak["window_start"]
    slot_items: Counter = Counter()
    window_items: Counter = Counter()
    slot_dates: set[date] = set()
    window_dates: set[date] = set()

    for o in db.query(Order).all():
        if _window_start(o.ts.hour) != start:
            continue
        try:
            items = json.loads(o.items_json)
        except Exception:
            continue
        window_dates.add(o.ts.date())
        for it in items:
            window_items[it["item"]] += it.get("qty", 1)
        if o.ts.weekday() == weekday:
            slot_dates.add(o.ts.date())
            for it in items:
                slot_items[it["item"]] += it.get("qty", 1)

    if not slot_dates or not window_dates:
        return []

    drivers = []
    for item, total in slot_items.most_common(limit * 2):
        expected = total / len(slot_dates)                 # per occurrence of this slot
        normal = window_items[item] / len(window_dates)    # per normal day, same window
        if expected < 1:
            continue
        change = ((expected - normal) / normal * 100) if normal else 0.0
        drivers.append({
            "item": item,
            "normal": int(round(normal)),
            "expected": int(round(expected)),
            "change_pct": round(change, 1),
        })
    drivers.sort(key=lambda d: -(d["expected"] - d["normal"]))
    return drivers[:limit]


def service_pressure(db, peak: dict) -> dict | None:
    """Whether complaints about speed cluster in this window.

    Reported as an association with both rates and counts. Being busy and having
    complaints at the same time does not prove one caused the other.
    """
    weekday, start = peak["weekday"], peak["window_start"]
    slot_total = slot_slow = other_total = other_slow = 0
    for r in db.query(Review).all():
        themes = json.loads(r.themes_json) if r.themes_json else []
        slow = "slow delivery/service" in themes
        in_slot = r.ts.weekday() == weekday and _window_start(r.ts.hour) == start
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
        "relative_pct": round((slot_rate / other_rate - 1) * 100, 0),
        "slot_n": slot_total,
        "other_n": other_total,
    }


def backtest(db, peak: dict, rounds: int = 4) -> dict | None:
    """Walk forward through history: for each of the last few occurrences,
    forecast it using only what was known before, then compare with what
    happened. Honest accuracy without waiting for the future to arrive."""
    per_slot, per_window = _slot_history(db)
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
            "top_products": drivers[:3],
            "slow_service_complaints_higher_by_pct": pressure["relative_pct"] if pressure else None,
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
    """Concrete, operational, deterministic — no money involved."""
    extra = peak["expected_orders"] - peak["baseline_orders"]
    items = [f"Prep extra {d['item']} (about {d['expected'] - d['normal']} more than a normal day)"
             for d in drivers[:3] if d["expected"] > d["normal"]]
    items.append(f"Packaging stock for roughly {extra} additional orders")
    items.append(f"Kitchen staffing for the {peak['window_label']} window")
    items.append("Delivery riders on standby before the window opens")
    return items


def forecast(db, today: date | None = None) -> dict | None:
    """The whole Demand Planning page, in one payload."""
    peak = detect_peak(db, today)
    if not peak:
        return None
    drivers = product_drivers(db, peak)
    pressure = service_pressure(db, peak)
    evidence = [
        f"{peak['comparable_above']} of the last {peak['comparable_total']} comparable "
        f"{peak['day_name']}s ran busier than a normal day in this window",
        f"Based on {peak['observations']} past {peak['day_name']}s in the "
        f"{peak['window_label']} window",
        f"A normal day sees about {peak['baseline_orders']} orders in this window; "
        f"{peak['day_name']}s see about {peak['expected_orders']}",
    ]
    if drivers:
        evidence.append(f"{drivers[0]['item']} accounts for the largest share of the increase")
    if peak["trend_up"]:
        evidence.append(f"Recent {peak['day_name']}s are trending busier still")

    return {
        "peak": peak,
        "drivers": drivers,
        "service_pressure": pressure,
        "evidence": evidence,
        "recommendation": _recommendation(peak, drivers, pressure),
        "checklist": preparation_checklist(peak, drivers),
        "accuracy": backtest(db, peak),
        "method": (
            "Forecast is the median of the most recent comparable windows in the "
            "merchant's own order history. Accuracy below is measured by re-forecasting "
            "past windows using only the data available before each one."
        ),
    }


def measure_plan(db, plan) -> dict:
    """Once the planned window has passed, compare the forecast with what happened."""
    target = datetime.fromisoformat(plan.target_date).date() \
        if isinstance(plan.target_date, str) else plan.target_date
    start = datetime.combine(target, datetime.min.time()) + timedelta(hours=plan.window_start)
    end = start + timedelta(hours=WINDOW_HOURS)
    if datetime.utcnow() < end:
        return {"measured": False, "note": "The planned window has not finished yet."}

    actual = db.query(Order).filter(Order.ts >= start, Order.ts < end).count()
    accuracy = max(0.0, 1 - abs(plan.expected_orders - actual) / actual) if actual else 0.0
    return {
        "measured": True,
        "forecast": plan.expected_orders,
        "actual": actual,
        "accuracy_pct": round(accuracy * 100, 1),
    }
