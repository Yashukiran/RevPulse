"""One-time structured extraction over all reviews (cached in DB columns).

Uses Haiku in batches of 20 reviews per call to keep cost low. Re-running
skips reviews that are already extracted, so the pass is resumable and never
paid for twice.

Run:  python -m app.agent.extraction   (from backend/, venv active)
"""

from __future__ import annotations

import json
import os

import anthropic

from ..db import SessionLocal
from ..models import Review

EXTRACTION_MODEL = "claude-haiku-4-5-20251001"
BATCH = 20

THEMES = [
    "slow delivery/service",
    "packaging issue",
    "food quality issue",
    "spice level",
    "portion size",
    "parking",
    "biryani praise",
    "food praise",
    "delivery praise",
    "value for money",
    "other",
]

PROMPT = """You label restaurant reviews. For each review below, output one JSON object.

Allowed themes (pick 1-3 that apply): {themes}

Fields per review:
- id: the review id (integer, copy it exactly)
- sentiment: "positive" | "negative" | "mixed" | "neutral"
- themes: array of allowed theme strings
- urgency: "urgent" (angry customer / churn risk / repeated failure), "important" (real recurring issue), "routine" (everything else)
- churn_signal: true only if the text suggests the customer may stop ordering (e.g. "thinking of switching", "not sure I will keep ordering", long-time customer now disappointed)

Reviews:
{reviews}

Reply with ONLY a JSON array of the objects, no other text."""


def extract_all(verbose: bool = True) -> int:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    db = SessionLocal()
    pending = db.query(Review).filter(Review.sentiment.is_(None)).order_by(Review.id).all()
    done = 0
    for i in range(0, len(pending), BATCH):
        chunk = pending[i : i + BATCH]
        payload = "\n".join(
            json.dumps({"id": r.id, "rating": r.rating, "text": r.text}) for r in chunk
        )
        msg = client.messages.create(
            model=EXTRACTION_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": PROMPT.format(themes=", ".join(THEMES), reviews=payload)}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        rows = {row["id"]: row for row in json.loads(text)}
        for r in chunk:
            row = rows.get(r.id)
            if not row:
                continue
            r.sentiment = row["sentiment"]
            r.themes_json = json.dumps(row["themes"])
            r.urgency = row["urgency"]
            r.churn_signal = bool(row["churn_signal"])
            done += 1
        db.commit()
        if verbose:
            print(f"extracted {min(i + BATCH, len(pending))}/{len(pending)}")
    db.close()
    return done


if __name__ == "__main__":
    from dotenv import load_dotenv
    from pathlib import Path

    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
    n = extract_all()
    print(f"done: {n} reviews extracted")
