"""Deduplicate FluNet rows and enforce natural-key uniqueness

Revision ID: 003
Revises: 002
Create Date: 2026-02-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Keep newest row per logical FluNet key, remove historical duplicates.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
              SELECT
                ctid,
                row_number() OVER (
                  PARTITION BY time, country_code, source, COALESCE(region,''), COALESCE(city,''), COALESCE(flu_type,'')
                  ORDER BY ingested_at DESC NULLS LAST, id DESC
                ) AS rn
              FROM flu_cases
              WHERE source='who_flunet'
            )
            DELETE FROM flu_cases f
            USING ranked r
            WHERE f.ctid = r.ctid
              AND r.rn > 1
            """
        )
    )

    # Enforce one row per FluNet natural key.
    op.create_index(
        "uq_flu_cases_who_flunet_natural",
        "flu_cases",
        [
            "time",
            "country_code",
            "source",
            sa.text("COALESCE(region, '')"),
            sa.text("COALESCE(city, '')"),
            sa.text("COALESCE(flu_type, '')"),
        ],
        unique=True,
        postgresql_where=sa.text("source = 'who_flunet'"),
    )


def downgrade() -> None:
    op.drop_index("uq_flu_cases_who_flunet_natural", table_name="flu_cases")
