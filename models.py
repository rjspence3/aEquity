"""Pydantic schemas for the aEquity analysis output."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class MetricDrillDown(BaseModel):
    """Evidence and calculation details for a single metric."""

    metric_name: str
    raw_value: float
    normalized_score: int = Field(ge=0, le=100)
    source: Literal["yfinance", "10-K", "calculated"]
    evidence: str
    confidence: Literal["high", "medium", "low"]


class PillarAnalysis(BaseModel):
    """Score and evidence for one of the four analysis pillars."""

    pillar_name: Literal["The Engine", "The Moat", "The Fortress", "Alignment"]
    score: int = Field(ge=0, le=100)
    metrics: list[MetricDrillDown]
    summary: str
    red_flags: list[str]


class GuruScorecard(BaseModel):
    """Complete analysis from one legendary investor's perspective."""

    guru_name: Literal[
        "Warren Buffett", "Peter Lynch", "Ben Graham", "Aswath Damodaran",
        "Charlie Munger", "Joel Greenblatt", "Howard Marks", "Terry Smith",
    ]
    score: int = Field(ge=0, le=100)
    verdict: Literal["Strong Buy", "Buy", "Hold", "Avoid", "Strong Avoid"]
    rationale: str
    key_metrics: list[MetricDrillDown]
    grade: str = ""  # letter grade (e.g. "B+"); empty string for legacy gurus


class CompanyAnalysis(BaseModel):
    """Complete analysis output for a single company."""

    ticker: str
    company_name: str
    analysis_date: date
    filing_date: date
    filing_type: Literal["10-K", "10-Q"]
    pillars: list[PillarAnalysis]
    gurus: list[GuruScorecard]
    overall_score: int = Field(ge=0, le=100)
    overall_grade: str = ""  # letter grade for the company overall
    confidence: Literal["high", "medium", "low"]
    errors: list[str] = []
    partial: bool = False
    price_targets: dict | None = None  # zones from services.price_targets


