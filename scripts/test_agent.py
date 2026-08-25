"""Terminal check: does the agent surface the planted patterns?

Run:  python scripts/test_agent.py   (uses backend venv)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "backend" / ".env")

from app.agent.loop import run_agent  # noqa: E402

PROMPT = (
    "Analyze this merchant's reviews and transactions. What are the biggest problems "
    "costing us money, the biggest opportunities, and which specific customers are at "
    "risk? Be specific with numbers."
)

result = run_agent(PROMPT)
print("=" * 70)
print("TOOL CALLS:")
for e in result["tool_events"]:
    print(f"  {e['tool']}({e['args']}) -> {e['verdict']}")
print("=" * 70)
print("stop_reason:", result.get("stop_reason"))
print(result["text"])
