"""Unit tests for pure (no I/O) pipeline scoring functions."""


# Import pure functions directly — no API calls involved
from models import MetricDrillDown
from pipeline import (
    _score_alignment,
    _score_buffett,
    _score_damodaran,
    _score_engine,
    _score_fortress,
    _score_graham,
    _score_lynch,
    _score_to_verdict,
)


def _metric(score: int) -> MetricDrillDown:
    return MetricDrillDown(
        metric_name="Test",
        raw_value=float(score),
        normalized_score=score,
        source="calculated",
        evidence="test",
        confidence="high",
    )


class TestBuffettScore:
    def test_all_inputs_available(self):
        score = _score_buffett(
            roic=0.20,
            fcf_conv=1.2,
            moat_score=80,
            nd_ebitda=0.5,
        )
        assert 0 <= score <= 100
        assert score > 60  # strong inputs → high score

    def test_all_none_returns_50(self):
        score = _score_buffett(None, None, 50, None)
        assert score == 50

    def test_partial_inputs(self):
        score = _score_buffett(roic=0.10, fcf_conv=None, moat_score=60, nd_ebitda=None)
        assert 0 <= score <= 100

    def test_weak_inputs_low_score(self):
        score = _score_buffett(
            roic=0.03,
            fcf_conv=0.3,
            moat_score=10,
            nd_ebitda=5.0,
        )
        assert score < 40


class TestLynchScore:
    def test_strong_growth_low_peg(self):
        score = _score_lynch(peg=0.5, earnings_growth=0.20, understandability=90)
        assert score >= 70

    def test_high_peg_reduces_score(self):
        score = _score_lynch(peg=3.0, earnings_growth=0.05, understandability=50)
        assert score < 50

    def test_none_peg_excludes_weight(self):
        score = _score_lynch(peg=None, earnings_growth=0.15, understandability=80)
        assert 0 <= score <= 100

    def test_all_none_returns_50(self):
        score = _score_lynch(None, None, 50)
        assert score == 50


class TestGrahamScore:
    def test_low_pb_high_cr(self):
        score = _score_graham(pb=1.0, current_ratio=2.5, earnings_growth=0.10)
        assert score >= 70

    def test_high_pb_reduces_score(self):
        score = _score_graham(pb=4.0, current_ratio=0.8, earnings_growth=-0.05)
        assert score < 40

    def test_all_none_returns_50(self):
        score = _score_graham(None, None, None)
        assert score == 50

    def test_negative_growth_lowers_score(self):
        score_pos = _score_graham(pb=2.0, current_ratio=1.5, earnings_growth=0.10)
        score_neg = _score_graham(pb=2.0, current_ratio=1.5, earnings_growth=-0.10)
        assert score_pos > score_neg


class TestDamodaranScore:
    def test_high_roic_low_peg(self):
        score = _score_damodaran(roic=0.25, peg=0.5, nd_ebitda=0.5)
        assert score >= 70

    def test_all_none_returns_50(self):
        score = _score_damodaran(None, None, None)
        assert score == 50


class TestScoreToVerdict:
    def test_strong_buy(self):
        assert _score_to_verdict(90) == "Strong Buy"
        assert _score_to_verdict(80) == "Strong Buy"

    def test_buy(self):
        assert _score_to_verdict(70) == "Buy"
        assert _score_to_verdict(65) == "Buy"

    def test_hold(self):
        assert _score_to_verdict(55) == "Hold"
        assert _score_to_verdict(45) == "Hold"

    def test_avoid(self):
        assert _score_to_verdict(35) == "Avoid"
        assert _score_to_verdict(30) == "Avoid"

    def test_strong_avoid(self):
        assert _score_to_verdict(29) == "Strong Avoid"
        assert _score_to_verdict(0) == "Strong Avoid"

    def test_boundary_80(self):
        assert _score_to_verdict(80) == "Strong Buy"
        assert _score_to_verdict(79) == "Buy"


class TestPillarScoreAggregation:
    def test_empty_metrics_returns_50(self):
        assert _score_engine([]) == 50
        assert _score_fortress([]) == 50
        assert _score_alignment([]) == 50

    def test_single_metric_returns_its_score(self):
        assert _score_engine([_metric(70)]) == 70

    def test_average_of_multiple(self):
        result = _score_fortress([_metric(60), _metric(80)])
        assert result == 70

    def test_all_zeros(self):
        assert _score_alignment([_metric(0), _metric(0)]) == 0

    def test_all_hundreds(self):
        assert _score_engine([_metric(100), _metric(100)]) == 100
