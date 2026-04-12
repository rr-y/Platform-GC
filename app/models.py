import uuid
from datetime import datetime, timezone, UTC

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Return current UTC time as naive datetime (timezone-unaware).
    Naive UTC is compatible with both SQLite (tests) and PostgreSQL (production).
    """
    return datetime.now(UTC).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    mobile_number: Mapped[str] = mapped_column(String(15), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(10), default="user")  # 'user' | 'admin'
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    coins: Mapped[list["CoinsLedger"]] = relationship(back_populates="user")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")
    notification_logs: Mapped[list["NotificationLog"]] = relationship(back_populates="user")


class CoinsLedger(Base):
    __tablename__ = "coins_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    coins: Mapped[int] = mapped_column(Integer, nullable=False)  # +N earned, -N redeemed
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'earned'|'redeemed'|'expired'|'adjusted'
    status: Mapped[str] = mapped_column(String(20), default="active")  # 'active'|'redeemed'|'expired'
    reference_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # transaction id
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expiry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemable_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship(back_populates="coins")

    __table_args__ = (
        Index("idx_coins_user_status", "user_id", "status"),
        Index("idx_coins_expiry", "expiry_at"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    order_ref: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    coins_earned: Mapped[int] = mapped_column(Integer, default=0)
    coins_used: Mapped[int] = mapped_column(Integer, default=0)
    discount_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    coupon_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("coupons.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="transactions")
    coupon: Mapped["Coupon | None"] = relationship(back_populates="transactions")

    __table_args__ = (
        Index("idx_txn_user_id", "user_id"),
        Index("idx_txn_order_ref", "order_ref"),
    )


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # 'flat'|'percentage'|'coins_bonus'
    discount_value: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    min_order_value: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    max_discount_cap: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    audience_type: Mapped[str] = mapped_column(String(20), default="all")  # 'all'|'new_users'|'inactive'
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    coupons: Mapped[list["Coupon"]] = relationship(back_populates="campaign")


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    campaign_id: Mapped[str] = mapped_column(String(36), ForeignKey("campaigns.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    is_auto_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses_count: Mapped[int] = mapped_column(Integer, default=0)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    campaign: Mapped["Campaign"] = relationship(back_populates="coupons")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="coupon")
    redemptions: Mapped[list["CouponRedemption"]] = relationship(back_populates="coupon")

    __table_args__ = (Index("idx_coupon_code", "code"),)


class CouponRedemption(Base):
    __tablename__ = "coupon_redemptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    coupon_id: Mapped[str] = mapped_column(String(36), ForeignKey("coupons.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(36), ForeignKey("transactions.id"), nullable=False)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    coupon: Mapped["Coupon"] = relationship(back_populates="redemptions")

    __table_args__ = (Index("idx_coupon_redemption_user_coupon", "user_id", "coupon_id"),)


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # 'sms'|'whatsapp'
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'otp'|'coins_expiry'|'campaign'
    status: Mapped[str] = mapped_column(String(20), default="pending")  # 'sent'|'failed'
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="notification_logs")
