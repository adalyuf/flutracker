"""Initial schema

Revision ID: 001
Revises: None
Create Date: 2026-02-06
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Countries lookup table
    op.create_table(
        "countries",
        sa.Column("code", sa.String(2), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("population", sa.BigInteger()),
        sa.Column("continent", sa.Text()),
        sa.Column("scraper_id", sa.Text()),
        sa.Column("last_scraped", sa.DateTime(timezone=True)),
        sa.Column("scrape_frequency", sa.Text(), server_default="daily"),
    )

    # Regions lookup table
    op.create_table(
        "regions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("country_code", sa.String(2), sa.ForeignKey("countries.code"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("lat", sa.Float()),
        sa.Column("lon", sa.Float()),
        sa.Column("population", sa.BigInteger()),
    )

    # Core flu cases table (will become hypertable)
    op.create_table(
        "flu_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("region", sa.Text()),
        sa.Column("city", sa.Text()),
        sa.Column("new_cases", sa.Integer(), nullable=False),
        sa.Column("flu_type", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_cases_country", "flu_cases", ["country_code", sa.text("time DESC")])
    op.create_index("idx_cases_region", "flu_cases", ["country_code", "region", sa.text("time DESC")])

    # Anomalies table
    op.create_table(
        "anomalies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("region", sa.Text()),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("z_score", sa.Float(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("severity", sa.Text()),
    )
    op.create_index("idx_anomalies_country", "anomalies", ["country_code", sa.text("detected_at DESC")])

    # Scrape log table
    op.create_table(
        "scrape_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scraper_id", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text()),
        sa.Column("records_fetched", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("scrape_log")
    op.drop_table("anomalies")
    op.drop_table("flu_cases")
    op.drop_table("regions")
    op.drop_table("countries")
