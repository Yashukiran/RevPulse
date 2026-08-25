"""Graceful-failure demo — scripted and reproducible (the on-camera moment).

Story: today's incentive budget has only ₹1,200 left. The merchant asks the
agent for a ₹2,000 campaign. Policy BLOCKS it (daily budget), the agent does
not crash — it explains the refusal in plain language and proposes a reduced
₹1,000 campaign, which parks for approval. We approve it; execution succeeds;
the idempotency ledger shows no duplicates.

Run:  python scripts/demo_failure.py
Then open the Audit Console in the dashboard to see the whole chain.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

from app import policy  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Approval, AuditLog, BudgetSpend, PaymentLink  # noqa: E402

db = SessionLocal()
today = datetime.utcnow().strftime("%Y-%m-%d")

# ---- 1. stage the constraint: ₹3,800 already spent today -> ₹1,200 left
spent = sum(r.amount_inr for r in db.query(BudgetSpend).filter_by(date=today))
if spent < 3800:
    db.add(BudgetSpend(date=today, amount_inr=3800 - spent,
                       note="demo: prior campaigns today"))
    db.commit()
print(f"[stage] daily budget ₹{policy.DAILY_BUDGET_INR:,}, spent today ₹3,800 "
      f"-> ₹1,200 remaining\n")

# ---- 2. merchant asks for a ₹2,000 campaign
from app.agent.loop import run_agent  # noqa: E402

prompt = ("Create a win-back campaign for 5 lapsed customers (customer ids "
          "230, 231, 232, 233, 234) offering 15% off biryani with a budget of "
          "₹2000. If the request is blocked by policy, explain why in plain "
          "language and then IMMEDIATELY submit the best compliant alternative "
          "for the same 5 customers within the remaining budget (do not ask me "
          "first — submit it so it lands in my approval queue).")
print(f"[merchant] {prompt}\n")
result = run_agent(prompt)

print("[agent tool calls]")
for e in result["tool_events"]:
    print(f"  {e['tool']}(budget={e['args'].get('budget_inr')}) -> {e['verdict']}"
          + (f"  [{e['rule']}]" if e["rule"] else ""))
print(f"\n[agent] {result['text']}\n")

# ---- 3. approve whatever the agent parked (the reduced campaign)
pending = (db.query(Approval).filter_by(status="pending")
           .order_by(Approval.id.desc()).first())
if not pending:
    print("[demo] nothing parked for approval — check the agent transcript above")
    sys.exit(1)

args = json.loads(pending.args_json)
print(f"[approval queue] #{pending.id}: {pending.tool} budget=₹{args.get('budget_inr')}")
assert int(args.get("budget_inr", 0)) <= 1200, "agent proposed over remaining budget!"

from app.routers.actions_api import approve  # noqa: E402

resp = approve(pending.id, db)
camp = resp["result"]
print(f"[merchant] APPROVED -> campaign {camp.get('offer_code')} created, "
      f"{len(camp.get('links', []))} real Razorpay test links\n")

# ---- 4. idempotency proof: approving/executing again cannot double-create
from app import actions  # noqa: E402

again = actions.execute_action(db, pending.tool, args)
reused = all(l.get("reused") for l in again.get("links", []))
print(f"[retry] executed the same approved action again -> "
      f"{'all links REUSED, zero duplicates' if reused else 'DUPLICATES CREATED (BUG)'}")

n = db.query(PaymentLink).filter(
    PaymentLink.offer_code == camp.get("offer_code")).count()
print(f"[ledger] payment links for {camp.get('offer_code')}: {n} "
      f"(= targeted customers, not doubled)")

print("\n[audit trail tail]")
for e in (db.query(AuditLog).order_by(AuditLog.id.desc()).limit(6).all())[::-1]:
    print(f"  #{e.id} {e.actor:<9} {e.tool:<28} {e.policy_verdict:<15} "
          f"{e.status:<10} {e.policy_rule_hit or ''}")

db.close()
print("\nDemo complete — open the Audit Console to replay this chain visually.")
