"""Add missing indexes for query performance

Revision ID: 002
Revises: 001
Create Date: 2026-02-11
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_cases_time", "flu_cases", [sa.text("time DESC")])
    op.create_index("idx_cases_source_time", "flu_cases", ["source", sa.text("time DESC")])
    op.create_index("idx_cases_flu_type", "flu_cases", ["country_code", "flu_type", sa.text("time DESC")])


def downgrade() -> None:
    op.drop_index("idx_cases_flu_type", table_name="flu_cases")
    op.drop_index("idx_cases_source_time", table_name="flu_cases")
    op.drop_index("idx_cases_time", table_name="flu_cases")
