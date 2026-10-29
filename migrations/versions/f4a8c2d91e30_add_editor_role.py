"""add editor role

Revision ID: f4a8c2d91e30
Revises: e62c7bd671a9
Create Date: 2026-10-29
"""
from typing import Sequence, Union

from alembic import op


revision: str = "f4a8c2d91e30"
down_revision: Union[str, Sequence[str], None] = "e62c7bd671a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO roles (id, name, code, description)
        VALUES (
          '00000000-0000-0000-0000-000000000003',
          'Editor',
          'editor',
          'Content editor'
        )
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM roles r
        WHERE r.id = '00000000-0000-0000-0000-000000000003'
          AND NOT EXISTS (SELECT 1 FROM users u WHERE u.role_id = r.id)
    """)
