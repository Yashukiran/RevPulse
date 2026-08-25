"""Razorpay SDK wrapper. Test mode only — real API objects, no real money.

Idempotency: every money call carries a deterministic idempotency key derived
from (tool, args). Before hitting Razorpay we check our own ledger for that
key; a retry therefore returns the existing object instead of double-creating.
The key is also sent as the payment link's reference_id, so even a race hits
Razorpay's own uniqueness check — belt and braces.
"""

from __future__ import annotations

import hashlib
import json
import os

import razorpay


def idempotency_key(tool: str, args: dict, discriminator: str = "") -> str:
    payload = json.dumps({"tool": tool, "args": args, "d": discriminator}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


_client: razorpay.Client | None = None


def client() -> razorpay.Client:
    global _client
    if _client is None:
        _client = razorpay.Client(
            auth=(os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"])
        )
    return _client


def create_payment_link(*, amount_inr: int, description: str, customer_name: str,
                        customer_email: str, customer_phone: str, reference_id: str,
                        notes: dict) -> dict:
    """Create a Razorpay payment link (test mode). Returns the raw API object."""
    return client().payment_link.create({
        "amount": amount_inr * 100,          # paise
        "currency": "INR",
        "description": description,
        "reference_id": reference_id,        # our idempotency key
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "contact": customer_phone,
        },
        "notify": {"sms": False, "email": False},   # demo: no real notifications
        "notes": {k: str(v) for k, v in notes.items()},
    })


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        return False
    try:
        razorpay.Utility(client()).verify_webhook_signature(
            body.decode(), signature, secret
        )
        return True
    except Exception:
        return False
