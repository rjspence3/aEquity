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
    _weighted_score,
)
from scoring_config import ALIGNMENT_WEIGHTS as _ALIGNMENT_WEIGHTS
from scoring_config import ENGINE_WEIGHTS as _ENGINE_WEIGHTS
from scoring_config import FORTRESS_WEIGHTS as _FORTRESS_WEIGHTS


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

    def test_degradation_only_moat_available(self):
        # moat_score=80, all quantitative inputs None.
        # Only component is (0.25, 80); total_weight=0.25 → score = 80.
        # Verifies "never silently shifts toward 50" — result must equal moat value.
        score = _score_buffett(None, None, 80, None)
        assert score == 80

    def test_degradation_weighted_average_of_available(self):
        # roic available → normalize_roic(0.25) = 100 (above ROIC_UPPER=0.20)
        # moat_score = 0
        # weights: roic=0.30, moat=0.25; total=0.55
        # expected = int((0.30*100 + 0.25*0) / 0.55) = int(54.54) = 54
        score = _score_buffett(roic=0.25, fcf_conv=None, moat_score=0, nd_ebitda=None)
        assert score == 54


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

    def test_degradation_only_understandability_available(self):
        # peg=None, earnings_growth=None → only understandability component (weight 0.30).
        # total_weight=0.30 → score = understandability value (not pulled toward 50).
        score = _score_lynch(peg=None, earnings_growth=None, understandability=90)
        assert score == 90


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

    def test_degradation_only_growth_available(self):
        # pb=None, current_ratio=None → only earnings_growth component (weight 0.30).
        # earnings_growth=0.10 > 0 → stability=100; score = 100.
        score = _score_graham(pb=None, current_ratio=None, earnings_growth=0.10)
        assert score == 100

    def test_degradation_negative_growth_only(self):
        # pb=None, current_ratio=None, earnings_growth=-0.05 → stability=0; score = 0.
        score = _score_graham(pb=None, current_ratio=None, earnings_growth=-0.05)
        assert score == 0


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


def _named_metric(name: str, score: int) -> MetricDrillDown:
    return MetricDrillDown(
        metric_name=name,
        raw_value=float(score),
        normalized_score=score,
        source="calculated",
        evidence="test",
        confidence="high",
    )


class TestPillarScoreAggregation:
    # ── Backward-compat: unknown metric names fall back to equal weighting ──

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

    # ── Named weights are applied for known metric names ────────────────────

    def test_engine_roic_weighted_more_than_gross_margin(self):
        # ROIC=100, Gross Margin=0 → should be closer to 60 than 50
        result = _score_engine([
            _named_metric("ROIC", 100),
            _named_metric("Gross Margin", 0),
        ])
        assert result == 60  # 0.60*100 + 0.40*0 = 60

    def test_fortress_missing_metric_renormalises_weights(self):
        # Only FCF Conversion present; its weight (0.40) renormalises to 1.0
        result = _score_fortress([_named_metric("FCF Conversion", 80)])
        assert result == 80

    def test_alignment_equal_weights(self):
        result = _score_alignment([
            _named_metric("Insider Ownership", 100),
            _named_metric("Shareholder Yield", 0),
        ])
        assert result == 50  # 0.50*100 + 0.50*0 = 50

    def test_weighted_score_unknown_name_equal_fallback(self):
        # Two unknown-name metrics should still average equally
        result = _weighted_score(
            [_named_metric("Unknown A", 40), _named_metric("Unknown B", 80)],
            _ENGINE_WEIGHTS,
        )
        assert result == 60

    def test_weight_dicts_cover_all_builder_metrics(self):
        # Catch any future rename in calculator_tools.py
        assert "ROIC" in _ENGINE_WEIGHTS
        assert "Gross Margin" in _ENGINE_WEIGHTS
        assert "FCF Conversion" in _FORTRESS_WEIGHTS
        assert "Net Debt / EBITDA" in _FORTRESS_WEIGHTS
        assert "ROIC" in _FORTRESS_WEIGHTS
        assert "Insider Ownership" in _ALIGNMENT_WEIGHTS
        assert "Shareholder Yield" in _ALIGNMENT_WEIGHTS
