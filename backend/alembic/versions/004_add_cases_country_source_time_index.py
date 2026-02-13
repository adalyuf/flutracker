"""Add composite flu_cases index for country+source+time

Revision ID: 004
Revises: 003
Create Date: 2026-02-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_cases_country_source_time",
        "flu_cases",
        ["country_code", "source", sa.text("time DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_cases_country_source_time", table_name="flu_cases")
