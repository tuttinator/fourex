"""add structured_data column to agent_memory

Revision ID: 20260417_000001
Revises: 20260415_000001
Create Date: 2026-04-17 00:00:01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260417_000001"
down_revision: str | None = "20260415_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_memory",
        sa.Column(
            "structured_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_memory", "structured_data")
