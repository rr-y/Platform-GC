"""offer banners

Revision ID: a3f91c2d8e47
Revises: bd16388e453a
Create Date: 2026-04-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f91c2d8e47"
down_revision: Union[str, None] = "bd16388e453a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add display fields to campaigns
    op.add_column("campaigns", sa.Column("image_url", sa.Text(), nullable=True))
    op.add_column("campaigns", sa.Column("description", sa.Text(), nullable=True))

    # User-specific offer eligibility table
    op.create_table(
        "campaign_user_eligibility",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.String(36),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_campaign_user"),
    )
    op.create_index(
        "idx_campaign_user_elig",
        "campaign_user_eligibility",
        ["user_id", "campaign_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_campaign_user_elig", table_name="campaign_user_eligibility")
    op.drop_table("campaign_user_eligibility")
    op.drop_column("campaigns", "description")
    op.drop_column("campaigns", "image_url")
