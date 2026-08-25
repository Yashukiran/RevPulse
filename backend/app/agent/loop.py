"""The agent loop. Deliberately small — this is the whole brain.

Every tool call the model makes goes through policy.check() first and is
written to the audit log BEFORE execution (write-ahead). The LLM never touches
Razorpay or the DB directly; it can only request tools.
"""

from __future__ import annotations

import json
import os

import anthropic

from .. import audit, policy
from ..db import SessionLocal
from .tools import TOOLS, execute_tool

AGENT_MODEL = "claude-sonnet-5"
MAX_TURNS = 15

SYSTEM = """You are RevPulse, the growth agent for Biryani House (Bengaluru restaurant, delivery).
You turn first-party reviews and transaction data into revenue actions for the merchant.

Rules:
- Ground every claim in tool data. Cite counts and sample sizes.
- Trends and correlations are ASSOCIATIONS, not causation — say so.
- Money/action tools are bounded by a deterministic policy engine; some requests will
  come back NEEDS_APPROVAL (parked for the merchant) or BLOCKED (with the rule). Never
  try to work around a verdict; explain it to the merchant in plain language and, when
  sensible, propose a smaller compliant alternative.
- Be concise and concrete. Amounts in INR."""


def run_agent(user_message: str, history: list | None = None) -> dict:
    """Run one agent conversation. Returns {text, tool_events, messages}."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msgs = list(history or []) + [{"role": "user", "content": user_message}]
    events = []
    db = SessionLocal()
    try:
        for _ in range(MAX_TURNS):
            resp = client.messages.create(
                model=AGENT_MODEL, max_tokens=1600, system=SYSTEM, messages=msgs, tools=TOOLS
            )
            reasoning = " ".join(b.text for b in resp.content if b.type == "text").strip()
            if resp.stop_reason != "tool_use":
                return {"text": reasoning, "tool_events": events, "messages": msgs}

            msgs.append({"role": "assistant", "content": resp.content})
            results = []
            for call in (b for b in resp.content if b.type == "tool_use"):
                verdict, rule = policy.check(call.name, call.input, db)
                entry = audit.write_ahead(db, actor="agent", tool=call.name, args=call.input,
                                          reasoning=reasoning, verdict=verdict, rule=rule)
                if verdict == policy.ALLOWED:
                    try:
                        result = execute_tool(call.name, call.input, db)
                        audit.complete(db, entry, status="success")
                    except Exception as e:  # tool failure is data, not a crash
                        result = {"error": str(e)}
                        audit.complete(db, entry, status="failed", error=str(e))
                elif verdict == policy.NEEDS_APPROVAL:
                    result = policy.queue_approval(db, entry, call.name, call.input, reasoning)
                    audit.complete(db, entry, status="awaiting_approval")
                else:  # BLOCKED
                    result = {"verdict": "BLOCKED", "rule": rule,
                              "note": "This action violates a hard policy bound and was not executed."}
                    audit.complete(db, entry, status="blocked")
                events.append({"tool": call.name, "args": call.input,
                               "verdict": verdict, "rule": rule})
                results.append({"type": "tool_result", "tool_use_id": call.id,
                                "content": json.dumps(result, default=str)})
            msgs.append({"role": "user", "content": results})
        return {"text": "Stopped: turn limit reached.", "tool_events": events, "messages": msgs}
    finally:
        db.close()
