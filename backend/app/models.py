from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    city: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(80))


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    price_inr: Mapped[int] = mapped_column(Integer)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant_id: Mapped[int] = mapped_column(ForeignKey("merchants.id"))
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(20))
    zone: Mapped[str] = mapped_column(String(40))  # delivery zone
    first_seen: Mapped[datetime] = mapped_column(DateTime)

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")
    reviews: Mapped[list["Review"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    amount_inr: Mapped[int] = mapped_column(Integer)
    items_json: Mapped[str] = mapped_column(Text)  # [{item, qty, price_inr}]
    zone: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="paid")  # paid/failed
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id"), nullable=True, index=True
    )  # set when the order came via a campaign payment link (attribution)

    customer: Mapped["Customer"] = relationship(back_populates="orders")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    rating: Mapped[int] = mapped_column(Integer)  # 1..5
    text: Mapped[str] = mapped_column(Text)

    # Filled by extraction pass (Haiku), cached forever
    sentiment: Mapped[str | None] = mapped_column(String(12), nullable=True)  # positive/negative/mixed/neutral
    themes_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # ["slow service", ...]
    urgency: Mapped[str | None] = mapped_column(String(12), nullable=True)  # urgent/important/routine
    churn_signal: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    reply_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_posted_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped["Customer"] = relationship(back_populates="reviews")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    kind: Mapped[str] = mapped_column(String(30))  # recovery_offer / campaign
    segment_desc: Mapped[str] = mapped_column(String(200))
    offer_desc: Mapped[str] = mapped_column(String(200))
    offer_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    discount_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_inr: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/completed/cancelled
    customer_ids_json: Mapped[str] = mapped_column(Text)  # targeted customer ids
    # customers deliberately withheld from the offer, to measure incrementality
    control_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class PaymentLink(Base):
    __tablename__ = "payment_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    razorpay_link_id: Mapped[str | None] = mapped_column(String(60), index=True)
    short_url: Mapped[str | None] = mapped_column(String(200))
    amount_inr: Mapped[int] = mapped_column(Integer)
    offer_code: Mapped[str | None] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="created")  # created/paid/failed/cancelled
    created_ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    paid_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(60), nullable=True)


class AuditLog(Base):
    """Write-ahead log: row is written BEFORE any execution, updated after."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(30))  # agent / merchant / system
    tool: Mapped[str] = mapped_column(String(60))
    args_json: Mapped[str] = mapped_column(Text)
    agent_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_verdict: Mapped[str] = mapped_column(String(20))  # ALLOWED/NEEDS_APPROVAL/BLOCKED
    policy_rule_hit: Mapped[str | None] = mapped_column(String(120), nullable=True)
    razorpay_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/success/failed/blocked/awaiting_approval
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audit_log.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    tool: Mapped[str] = mapped_column(String(60))
    args_json: Mapped[str] = mapped_column(Text)
    agent_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/approved/rejected
    decided_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BudgetSpend(Base):
    """Daily incentive spend ledger feeding the policy engine's budget caps."""

    __tablename__ = "budget_spend"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    amount_inr: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Opportunity(Base):
    """A revenue opportunity the agent found on its own.

    Carries the evidence it was derived from, the money maths (deterministic),
    the concrete action it proposes, the policy verdict that action would get,
    and — once executed — the measured outcome. This is the unit the merchant
    actually approves.
    """

    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(40))          # churn_risk_winback
    title: Mapped[str] = mapped_column(String(200))
    rationale: Mapped[str] = mapped_column(Text)           # plain-language why (agent-written)
    evidence_json: Mapped[str] = mapped_column(Text)       # reviews + transactions behind it
    customer_ids_json: Mapped[str] = mapped_column(Text)

    # money maths — computed in Python, never by the model
    revenue_at_risk_inr: Mapped[int] = mapped_column(Integer, default=0)
    # what ONE returning order from each targeted customer is worth — the honest
    # upper bound of what this intervention can actually recover
    recoverable_revenue_inr: Mapped[int] = mapped_column(Integer, default=0)
    expected_revenue_inr: Mapped[int] = mapped_column(Integer, default=0)
    max_exposure_inr: Mapped[int] = mapped_column(Integer, default=0)
    assumed_redemption_rate: Mapped[float] = mapped_column(Float, default=0.0)

    # the concrete action proposed, and what the policy engine says about it
    proposed_tool: Mapped[str] = mapped_column(String(60))
    proposed_args_json: Mapped[str] = mapped_column(Text)
    policy_verdict: Mapped[str] = mapped_column(String(20))
    policy_rule_hit: Mapped[str | None] = mapped_column(String(200), nullable=True)
    excluded_note: Mapped[str | None] = mapped_column(String(300), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    # open / awaiting_approval / approved / executed / rejected / failed / expired
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"), nullable=True)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approvals.id"), nullable=True)
    audit_id: Mapped[int | None] = mapped_column(ForeignKey("audit_log.id"), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OfferRedemption(Base):
    """Tracks offers sent/redeemed per customer — feeds frequency cap and dedupe rules."""

    __tablename__ = "offer_redemptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"))
    sent_ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    redeemed_ts: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DemandPlan(Base):
    """An operational preparation plan for a forecast busy window.

    Deliberately carries no money: no offer, no discount, no Razorpay object.
    The forecast is snapshotted at creation so it can be honestly compared with
    what actually happened, rather than quietly re-forecast after the fact.
    """

    __tablename__ = "demand_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    target_date: Mapped[str] = mapped_column(String(10), index=True)   # YYYY-MM-DD
    day_name: Mapped[str] = mapped_column(String(12))
    window_start: Mapped[int] = mapped_column(Integer)
    window_label: Mapped[str] = mapped_column(String(20))

    expected_orders: Mapped[int] = mapped_column(Integer)
    baseline_orders: Mapped[int] = mapped_column(Integer)
    uplift_pct: Mapped[float] = mapped_column(Float)
    confidence: Mapped[str] = mapped_column(String(10))

    drivers_json: Mapped[str] = mapped_column(Text)
    checklist_json: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned/measured
