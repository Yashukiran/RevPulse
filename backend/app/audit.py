"""Write-ahead audit trail.

Every tool call is written here BEFORE anything executes, then updated with
the outcome — so even crashes and failures leave a record. Each write is also
broadcast to the dashboard's live audit console over WebSocket.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from .models import AuditLog

# WebSocket subscribers (set by main.py); broadcast is best-effort and never
# blocks or fails the audited action itself.
_subscribers: set = set()
_loop: asyncio.AbstractEventLoop | None = None


def register_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def subscribe(ws) -> None:
    _subscribers.add(ws)


def unsubscribe(ws) -> None:
    _subscribers.discard(ws)


def _broadcast(entry: AuditLog) -> None:
    if not _subscribers or _loop is None:
        return
    payload = json.dumps(serialize(entry), default=str)

    async def send_all():
        dead = []
        for ws in list(_subscribers):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _subscribers.discard(ws)

    try:
        asyncio.run_coroutine_threadsafe(send_all(), _loop)
    except Exception:
        pass


def serialize(e: AuditLog) -> dict:
    return {
        "id": e.id, "ts": e.ts.isoformat(), "actor": e.actor, "tool": e.tool,
        "args": json.loads(e.args_json) if e.args_json else {},
        "agent_reasoning": e.agent_reasoning, "policy_verdict": e.policy_verdict,
        "policy_rule_hit": e.policy_rule_hit, "razorpay_ref": e.razorpay_ref,
        "status": e.status, "error": e.error,
        "completed_ts": e.completed_ts.isoformat() if e.completed_ts else None,
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
