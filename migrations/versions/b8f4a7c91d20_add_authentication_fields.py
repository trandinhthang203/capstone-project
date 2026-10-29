"""add authentication fields and seed system roles

Revision ID: b8f4a7c91d20
Revises: 10a45c00385a
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b8f4a7c91d20"
down_revision: Union[str, Sequence[str], None] = "10a45c00385a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing accounts are intentionally locked with an invalid hash; they must
    # receive a password through a controlled reset flow before they can log in.
    op.add_column("users", sa.Column("password_hash", sa.String(), nullable=False, server_default="!"))
    op.alter_column("users", "password_hash", server_default=None)
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))

    op.execute("""
        INSERT INTO roles (id, name, code, description)
        VALUES
          ('00000000-0000-0000-0000-000000000001', 'Administrator', 'admin', 'System administrator'),
          ('00000000-0000-0000-0000-000000000002', 'User', 'user', 'Standard user')
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM roles r
        WHERE r.id IN ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002')
          AND NOT EXISTS (SELECT 1 FROM users u WHERE u.role_id = r.id)
    """)
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "password_hash")
