from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, BigInteger, Float, Text, DateTime,
    ForeignKey, CheckConstraint, Index, UniqueConstraint
)
from sqlalchemy.orm import relationship
from backend.app.database import Base


class Country(Base):
    __tablename__ = "countries"

    code = Column(String(2), primary_key=True)
    name = Column(Text, nullable=False)
    population = Column(BigInteger)
    continent = Column(Text)
    scraper_id = Column(Text)
    last_scraped = Column(DateTime(timezone=True))
    scrape_frequency = Column(Text, default="daily")

    regions = relationship("Region", back_populates="country")


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    country_code = Column(String(2), ForeignKey("countries.code"), nullable=False)
    name = Column(Text, nullable=False)
    lat = Column(Float)
    lon = Column(Float)
    population = Column(BigInteger)

    country = relationship("Country", back_populates="regions")


class FluCase(Base):
    __tablename__ = "flu_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(DateTime(timezone=True), nullable=False)
    country_code = Column(String(2), nullable=False)
    region = Column(Text)
    city = Column(Text)
    new_cases = Column(Integer, nullable=False)
    flu_type = Column(Text)  # H1N1, H3N2, B/Victoria, B/Yamagata, unknown
    source = Column(Text, nullable=False)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        Index("idx_cases_country", "country_code", time.desc()),
        Index("idx_cases_country_source_time", "country_code", "source", time.desc()),
        Index("idx_cases_region", "country_code", "region", time.desc()),
        Index("idx_cases_time", time.desc()),
        Index("idx_cases_source_time", "source", time.desc()),
        Index("idx_cases_flu_type", "country_code", "flu_type", time.desc()),
    )


class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    detected_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    country_code = Column(String(2), nullable=False)
    region = Column(Text)
    metric = Column(Text, nullable=False)
    z_score = Column(Float, nullable=False)
    description = Column(Text)
    severity = Column(
        Text,
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')"),
    )

    __table_args__ = (
        Index("idx_anomalies_country", "country_code", detected_at.desc()),
    )


class ScrapeLog(Base):
    __tablename__ = "scrape_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scraper_id = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    status = Column(
        Text,
        CheckConstraint("status IN ('running', 'success', 'error')"),
    )
    records_fetched = Column(Integer, default=0)
    error_message = Column(Text)


class GenomicSequence(Base):
    __tablename__ = "genomic_sequences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sample_date = Column(DateTime(timezone=True), nullable=False)
    country_code = Column(String(2))
    country_name = Column(Text)
    lineage = Column(Text, nullable=False)  # h3n2, h1n1pdm, vic, yam
    clade = Column(Text)
    strain_name = Column(Text, nullable=False)
    source = Column(Text, nullable=False, default="nextstrain")
    source_dataset = Column(Text, nullable=False)
    inserted_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("source_dataset", "strain_name", name="uq_genomic_dataset_strain"),
        Index("idx_genomic_sample_date", sample_date.desc()),
        Index("idx_genomic_country_date", "country_code", sample_date.desc()),
        Index("idx_genomic_lineage_date", "lineage", sample_date.desc()),
        Index("idx_genomic_clade_date", "clade", sample_date.desc()),
    )
