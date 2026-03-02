"""Unit tests for Pydantic schema validation."""

from datetime import date

import pytest
from pydantic import ValidationError

from models import (
    AnalysisError,
    CompanyAnalysis,
    GuruScorecard,
    MetricDrillDown,
    PillarAnalysis,
)


def _sample_metric() -> MetricDrillDown:
    return MetricDrillDown(
        metric_name="ROIC",
        raw_value=18.5,
        normalized_score=89,
        source="calculated",
        evidence="ROIC = 18.5%",
        confidence="high",
    )


def _sample_pillar() -> PillarAnalysis:
    return PillarAnalysis(
        pillar_name="The Engine",
        score=75,
        metrics=[_sample_metric()],
        summary="Strong profitability.",
        red_flags=[],
    )


def _sample_guru() -> GuruScorecard:
    return GuruScorecard(
        guru_name="Warren Buffett",
        score=80,
        verdict="Strong Buy",
        rationale="Durable moat with high ROIC.",
        key_metrics=[_sample_metric()],
    )


class TestMetricDrillDown:
    def test_valid_creation(self):
        m = _sample_metric()
        assert m.normalized_score == 89

    def test_score_below_0_raises(self):
        with pytest.raises(ValidationError):
            MetricDrillDown(
                metric_name="X",
                raw_value=1.0,
                normalized_score=-1,
                source="yfinance",
                evidence="test",
                confidence="high",
            )

    def test_score_above_100_raises(self):
        with pytest.raises(ValidationError):
            MetricDrillDown(
                metric_name="X",
                raw_value=1.0,
                normalized_score=101,
                source="yfinance",
                evidence="test",
                confidence="high",
            )

    def test_invalid_source_raises(self):
        with pytest.raises(ValidationError):
            MetricDrillDown(
                metric_name="X",
                raw_value=1.0,
                normalized_score=50,
                source="bloomberg",  # invalid
                evidence="test",
                confidence="high",
            )


class TestPillarAnalysis:
    def test_invalid_pillar_name_raises(self):
        with pytest.raises(ValidationError):
            PillarAnalysis(
                pillar_name="Unknown Pillar",
                score=50,
                metrics=[],
                summary="test",
                red_flags=[],
            )

    def test_score_boundaries(self):
        p = _sample_pillar()
        assert 0 <= p.score <= 100


class TestGuruScorecard:
    def test_invalid_guru_raises(self):
        with pytest.raises(ValidationError):
            GuruScorecard(
                guru_name="George Soros",  # not in Literal
                score=70,
                verdict="Buy",
                rationale="test",
                key_metrics=[],
            )

    def test_invalid_verdict_raises(self):
        with pytest.raises(ValidationError):
            GuruScorecard(
                guru_name="Warren Buffett",
                score=70,
                verdict="Maybe",  # invalid
                rationale="test",
                key_metrics=[],
            )


class TestCompanyAnalysis:
    def test_full_valid_analysis(self):
        analysis = CompanyAnalysis(
            ticker="AAPL",
            company_name="Apple Inc.",
            analysis_date=date.today(),
            filing_date=date(2024, 11, 1),
            filing_type="10-K",
            pillars=[
                PillarAnalysis(
                    pillar_name=name,
                    score=70,
                    metrics=[],
                    summary="test",
                    red_flags=[],
                )
                for name in ["The Engine", "The Moat", "The Fortress", "Alignment"]
            ],
            gurus=[_sample_guru()],
            overall_score=75,
            confidence="high",
        )
        assert analysis.ticker == "AAPL"
        assert not analysis.partial

    def test_partial_flag_defaults_false(self):
        a = CompanyAnalysis(
            ticker="X",
            company_name="X Corp",
            analysis_date=date.today(),
            filing_date=date.today(),
            filing_type="10-K",
            pillars=[],
            gurus=[],
            overall_score=50,
            confidence="low",
        )
        assert a.partial is False

    def test_overall_score_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            CompanyAnalysis(
                ticker="X",
                company_name="X Corp",
                analysis_date=date.today(),
                filing_date=date.today(),
                filing_type="10-K",
                pillars=[],
                gurus=[],
                overall_score=150,  # invalid
                confidence="low",
            )


class TestAnalysisError:
    def test_valid_error(self):
        err = AnalysisError(
            ticker="AAPL",
            error_type="rate_limit",
            message="429 Too Many Requests",
        )
        assert err.partial_result is None

    def test_invalid_error_type_raises(self):
        with pytest.raises(ValidationError):
            AnalysisError(
                ticker="AAPL",
                error_type="network_error",  # not in Literal
                message="test",
            )
