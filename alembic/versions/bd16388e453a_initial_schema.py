"""initial schema

Revision ID: bd16388e453a
Revises:
Create Date: 2026-04-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bd16388e453a"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mobile_number", sa.String(15), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("role", sa.String(10), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "campaigns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("discount_value", sa.Numeric(10, 2), nullable=True),
        sa.Column("min_order_value", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("max_discount_cap", sa.Numeric(10, 2), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("audience_type", sa.String(20), nullable=False, server_default="all"),
        sa.Column("usage_limit", sa.Integer, nullable=True),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "coupons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("campaign_id", sa.String(36), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("code", sa.String(30), nullable=False, unique=True),
        sa.Column("is_auto_apply", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("max_uses", sa.Integer, nullable=True),
        sa.Column("uses_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("per_user_limit", sa.Integer, nullable=False, server_default="1"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_coupon_code", "coupons", ["code"])

    op.create_table(
        "coins_ledger",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("coins", sa.Integer, nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("reference_id", sa.String(36), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expiry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemable_after", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("idx_coins_user_status", "coins_ledger", ["user_id", "status"])
    op.create_index("idx_coins_expiry", "coins_ledger", ["expiry_at"])

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_ref", sa.String(100), nullable=True, unique=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("coins_earned", sa.Integer, nullable=False, server_default="0"),
        sa.Column("coins_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("discount_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("coupon_id", sa.String(36), sa.ForeignKey("coupons.id"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_txn_user_id", "transactions", ["user_id"])
    op.create_index("idx_txn_order_ref", "transactions", ["order_ref"])

    op.create_table(
        "coupon_redemptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("coupon_id", sa.String(36), sa.ForeignKey("coupons.id"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("transaction_id", sa.String(36), sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_coupon_redemption_user_coupon", "coupon_redemptions", ["user_id", "coupon_id"])

    op.create_table(
        "notification_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("notification_logs")
    op.drop_table("coupon_redemptions")
    op.drop_table("transactions")
    op.drop_index("idx_coins_user_status", "coins_ledger")
    op.drop_index("idx_coins_expiry", "coins_ledger")
    op.drop_table("coins_ledger")
    op.drop_index("idx_coupon_code", "coupons")
    op.drop_table("coupons")
    op.drop_table("campaigns")
    op.drop_table("users")
