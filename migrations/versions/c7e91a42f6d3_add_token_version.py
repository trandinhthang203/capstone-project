"""add token version for access-token revocation

Revision ID: c7e91a42f6d3
Revises: b8f4a7c91d20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c7e91a42f6d3"
down_revision: Union[str, Sequence[str], None] = "b8f4a7c91d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
