"""add push_token to users

Revision ID: c4e82fa19b73
Revises: a3f91c2d8e47
Create Date: 2026-04-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e82fa19b73"
down_revision: Union[str, None] = "a3f91c2d8e47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("push_token", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "push_token")
