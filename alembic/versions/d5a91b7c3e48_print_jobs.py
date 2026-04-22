"""print_jobs table

Revision ID: d5a91b7c3e48
Revises: c4e82fa19b73
Create Date: 2026-04-21

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5a91b7c3e48"
down_revision: Union[str, None] = "c4e82fa19b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "print_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(50), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.Text, nullable=True),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("selected_pages", postgresql.JSONB, nullable=True),
        sa.Column("color_mode", sa.String(10), nullable=True),
        sa.Column("copies", sa.Integer, nullable=True),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=True),
        sa.Column("coins_to_redeem", sa.Integer, nullable=False, server_default="0"),
        sa.Column("coin_value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("final_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("pickup_otp", sa.CHAR(4), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("transaction_id", sa.String(36), sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("printed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_print_user_status", "print_jobs", ["user_id", "status"])
    op.create_index("idx_print_queued", "print_jobs", ["status", "queued_at"])
    # Partial unique index: pickup OTP only needs to be unique among jobs the
    # admin might currently be looking up.
    op.execute(
        "CREATE UNIQUE INDEX idx_print_active_pickup_otp "
        "ON print_jobs (pickup_otp) "
        "WHERE status IN ('queued','printing','printed')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_print_active_pickup_otp")
    op.drop_index("idx_print_queued", "print_jobs")
    op.drop_index("idx_print_user_status", "print_jobs")
    op.drop_table("print_jobs")
