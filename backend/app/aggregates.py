"""One pass over the order table, cached — the in-memory stand-in for the
materialised views this would use in production.

Both the transaction view and the demand forecast need totals over every order,
and each was computing them from scratch on every request: 43,909 rows read and
43,909 baskets JSON-parsed, several times per page. On a small instance that is
ten seconds of pure CPU for numbers that had not changed.

So the pass happens once and the result is reused until the order table
actually changes. `_fingerprint` is the guard: row count plus highest id, which
one cheap query answers. Any write that adds an order — a campaign payment
attributed by the webhook, a review submitted through the feedback form — moves
the fingerprint and the next read recomputes. Nothing stale can survive a write,
which is why this is a cache rather than a snapshot.

The arithmetic here is deliberately identical to the code it replaced; only the
number of times it runs has changed.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import func

from .models import Order

WINDOW_HOURS = 2


def _window_start(hour: int) -> int:
    return (hour // WINDOW_HOURS) * WINDOW_HOURS


class OrderAggregates:
    """Everything the read paths need, derived in a single pass."""

    def __init__(self) -> None:
        # month -> {revenue_inr, orders}
        self.monthly: dict[str, dict] = defaultdict(lambda: {"revenue_inr": 0, "orders": 0})
        # item name -> revenue
        self.item_revenue: Counter = Counter()
        # (weekday, window_start) -> {date: order count}
        self.slot_dates: dict[tuple[int, int], dict[date, int]] = defaultdict(
            lambda: defaultdict(int))
        # window_start -> {date: order count}   (the "normal day" baseline)
        self.window_dates: dict[int, dict[date, int]] = defaultdict(lambda: defaultdict(int))
        # The forecast counts every order. The item averages below divide by the
        # number of days whose baskets could actually be read, so they are
        # tracked separately — an unreadable basket must not inflate a divisor
        # it contributed no items to.
        # window_start -> item -> qty
        self.window_items: dict[int, Counter] = defaultdict(Counter)
        # (weekday, window_start) -> item -> qty
        self.slot_items: dict[tuple[int, int], Counter] = defaultdict(Counter)
        self.basket_window_days: dict[int, set[date]] = defaultdict(set)
        self.basket_slot_days: dict[tuple[int, int], set[date]] = defaultdict(set)
        self.slot_orders: Counter = Counter()      # (weekday, window) -> orders
        self.slot_revenue: Counter = Counter()     # (weekday, window) -> revenue
        self.slot_item_count: Counter = Counter()  # (weekday, window) -> plates


def _fingerprint(db) -> tuple[int, int]:
    """Cheap identity for the order table: (row count, highest id)."""
    n, top = db.query(func.count(Order.id), func.max(Order.id)).one()
    return int(n or 0), int(top or 0)


_cached: OrderAggregates | None = None
_cached_for: tuple[int, int] | None = None


def build(db) -> OrderAggregates:
    """Return the aggregates, recomputing only if the order table changed."""
    global _cached, _cached_for

    fp = _fingerprint(db)
    if _cached is not None and _cached_for == fp:
        return _cached

    agg = OrderAggregates()
    for ts, amount_inr, items_json in db.query(
        Order.ts, Order.amount_inr, Order.items_json
    ).all():
        month = ts.strftime("%Y-%m")
        agg.monthly[month]["revenue_inr"] += amount_inr
        agg.monthly[month]["orders"] += 1

        start = _window_start(ts.hour)
        day = ts.date()
        weekday = ts.weekday()
        slot = (weekday, start)

        # Order counts per dated slot: every order, readable basket or not.
        agg.slot_dates[slot][day] += 1
        agg.window_dates[start][day] += 1

        try:
            items = json.loads(items_json)
        except Exception:
            continue

        # From here on, only orders whose basket could be read.
        agg.basket_window_days[start].add(day)
        agg.basket_slot_days[slot].add(day)
        agg.slot_orders[slot] += 1
        agg.slot_revenue[slot] += amount_inr

        for it in items:
            name = it["item"]
            qty = it.get("qty", 1)
            # Revenue uses the stored price; the demand view counts plates.
            agg.item_revenue[name] += qty * it.get("price_inr", 0)
            agg.window_items[start][name] += qty
            agg.slot_items[slot][name] += qty
            agg.slot_item_count[slot] += qty

    _cached, _cached_for = agg, fp
    return agg


def invalidate() -> None:
    """Force a rebuild on the next read. The fingerprint makes this unnecessary
    in normal operation; it exists for tests that rewrite history in place."""
    global _cached, _cached_for
    _cached = _cached_for = None
