"""Write-ahead audit trail.

Every tool call is written here BEFORE anything executes, then updated with
the outcome — so even crashes and failures leave a record. Each write is also
broadcast to the dashboard's live audit console over WebSocket.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from .db import utc_iso
from .models import AuditLog

# WebSocket subscribers (set by main.py); broadcast is best-effort and never
# blocks or fails the audited action itself.
_subscribers: set = set()
_review_subscribers: set = set()
_loop: asyncio.AbstractEventLoop | None = None


def register_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe(ws) -> None:
    _subscribers.add(ws)


def unsubscribe(ws) -> None:
    _subscribers.discard(ws)


def subscribe_reviews(ws) -> None:
    _review_subscribers.add(ws)


def unsubscribe_reviews(ws) -> None:
    _review_subscribers.discard(ws)


def broadcast_review(payload: dict) -> None:
    """Push a live-review event to dashboard subscribers (best-effort)."""
    _send_to(_review_subscribers, json.dumps(payload, default=str))


def broadcast_opportunity(payload: dict) -> None:
    """Push an agent-found opportunity to dashboard subscribers (best-effort)."""
    _send_to(_review_subscribers,
             json.dumps({"type": "opportunity", "opportunity": payload}, default=str))


def _send_to(subscribers: set, payload: str) -> None:
    if not subscribers or _loop is None:
        return

    async def send_all():
        dead = []
        for ws in list(subscribers):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            subscribers.discard(ws)

    try:
        asyncio.run_coroutine_threadsafe(send_all(), _loop)
    except Exception:
        pass


def _broadcast(entry: AuditLog) -> None:
    _send_to(_subscribers, json.dumps(serialize(entry), default=str))


def serialize(e: AuditLog) -> dict:
    return {
        "id": e.id, "ts": utc_iso(e.ts), "actor": e.actor, "tool": e.tool,
        "args": json.loads(e.args_json) if e.args_json else {},
        "agent_reasoning": e.agent_reasoning, "policy_verdict": e.policy_verdict,
        "policy_rule_hit": e.policy_rule_hit, "razorpay_ref": e.razorpay_ref,
        "status": e.status, "error": e.error,
        "completed_ts": utc_iso(e.completed_ts),
    }


def write_ahead(db, actor: str, tool: str, args: dict, reasoning: str | None,
                verdict: str, rule: str | None) -> AuditLog:
    entry = AuditLog(actor=actor, tool=tool, args_json=json.dumps(args or {}),
                     agent_reasoning=reasoning or None, policy_verdict=verdict,
                     policy_rule_hit=rule, status="pending")
    db.add(entry)
    db.commit()          # durable BEFORE execution — that is the whole point
    _broadcast(entry)
    return entry


def complete(db, entry: AuditLog, status: str, razorpay_ref: str | None = None,
             error: str | None = None) -> None:
    entry.status = status
    entry.razorpay_ref = razorpay_ref
    entry.error = error
    entry.completed_ts = datetime.utcnow()
    db.commit()
    _broadcast(entry)
