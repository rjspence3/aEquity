"""Tests for validation/metric_accuracy.py."""

from datetime import date
from unittest.mock import MagicMock, patch

from models import CompanyAnalysis, GuruScorecard, MetricDrillDown, PillarAnalysis


def _make_metric(
    name: str,
    raw: float = 0.0,
    score: int = 50,
    source: str = "calculated",
) -> MetricDrillDown:
    return MetricDrillDown(
        metric_name=name,
        raw_value=raw,
        normalized_score=score,
        source=source,  # type: ignore[arg-type]
        evidence=f"{name} = {raw}",
        confidence="high",
    )


def _make_analysis_with_roic(roic_decimal: float) -> CompanyAnalysis:
    """Build a synthetic analysis with ROIC stored as pipeline raw_value (pct form)."""
    # Pipeline stores ROIC raw_value as roic * 100 in MetricDrillDown
    roic_pct = roic_decimal * 100
    roic_metric = _make_metric("ROIC", raw=roic_pct, score=80)

    pillar_engine = PillarAnalysis(
        pillar_name="The Engine",
        score=80,
        metrics=[roic_metric],
        summary="Engine.",
        red_flags=[],
    )
    pillar_moat = PillarAnalysis(
        pillar_name="The Moat",
        score=70,
        metrics=[_make_metric("Moat Score", raw=70.0, score=70, source="10-K")],
        summary="Moat.",
        red_flags=[],
    )
    pillar_fortress = PillarAnalysis(
        pillar_name="The Fortress",
        score=75,
        metrics=[_make_metric("ROIC", raw=roic_pct, score=80)],
        summary="Fortress.",
        red_flags=[],
    )
    pillar_alignment = PillarAnalysis(
        pillar_name="Alignment",
        score=60,
        metrics=[],
        summary="Aligned.",
        red_flags=[],
    )
    guru = GuruScorecard(
        guru_name="Warren Buffett",
        score=75,
        verdict="Buy",
        rationale="Good ROIC.",
        key_metrics=[
            _make_metric("ROIC", raw=roic_pct, score=80),
        ],
    )
    return CompanyAnalysis(
        ticker="AAPL",
        company_name="Apple Inc.",
        analysis_date=date(2025, 1, 1),
        filing_date=date(2024, 10, 1),
        filing_type="10-K",
        pillars=[pillar_engine, pillar_moat, pillar_fortress, pillar_alignment],
        gurus=[guru],
        overall_score=75,
        confidence="high",
    )


class TestCompareMetrics:
    def test_compare_metrics_flags_large_diff(self):
        """Flags metrics where the difference exceeds 10%."""
        from validation.metric_accuracy import compare_metrics

        ours = {"roic_pct": 10.0}
        reference = {"roic_pct": 20.0, "source": "test", "notes": "", "verified": True}
        results = compare_metrics(ours, reference)

        roic_result = next(r for r in results if r["metric"] == "roic_pct")
        assert roic_result["pass_fail"] == "FAIL"
        assert roic_result["pct_diff"] == 50.0  # (10 vs 20) = 50% diff

    def test_compare_metrics_passes_small_diff(self):
        """Passes metrics within 10% tolerance."""
        from validation.metric_accuracy import compare_metrics

        ours = {"roic_pct": 10.5}
        reference = {"roic_pct": 10.0, "source": "test", "notes": "", "verified": True}
        results = compare_metrics(ours, reference)

        roic_result = next(r for r in results if r["metric"] == "roic_pct")
        assert roic_result["pass_fail"] == "PASS"
        assert roic_result["pct_diff"] == 5.0

    def test_compare_metrics_skips_null_reference(self):
        """Skips metrics where the reference value is None (not applicable for ticker type)."""
        from validation.metric_accuracy import compare_metrics

        ours = {"current_ratio": 1.5}
        reference = {
            "current_ratio": None,
            "roic_pct": 20.0,
            "source": "test",
            "notes": "",
            "verified": True,
        }
        results = compare_metrics(ours, reference)

        metric_names = [r["metric"] for r in results]
        assert "current_ratio" not in metric_names
        assert "roic_pct" in metric_names

    def test_compare_metrics_marks_missing_as_missing(self):
        """Returns MISSING when our pipeline has no value for a metric."""
        from validation.metric_accuracy import compare_metrics

        ours = {}  # no metrics
        reference = {"roic_pct": 20.0, "source": "test", "notes": "", "verified": True}
        results = compare_metrics(ours, reference)

        roic_result = next(r for r in results if r["metric"] == "roic_pct")
        assert roic_result["pass_fail"] == "MISSING"
        assert roic_result["our_value"] is None

    def test_compare_metrics_all_null_reference_returns_empty(self):
        """Returns empty list when all reference values are None."""
        from validation.metric_accuracy import compare_metrics

        ours = {"roic_pct": 10.0, "current_ratio": 1.5}
        reference = {
            "roic_pct": None,
            "fcf_conversion": None,
            "net_debt_ebitda": None,
            "peg_ratio": None,
            "price_to_book": None,
            "current_ratio": None,
            "gross_margin_pct": None,
            "source": "test",
            "notes": "Bank — not applicable",
            "verified": True,
        }
        results = compare_metrics(ours, reference)
        assert results == []


class TestGetOurMetrics:
    def test_get_our_metrics_converts_roic_to_pct(self):
        """Returns roic_pct as percentage (e.g., 18.0) when pipeline stores it as pct in raw_value."""
        from validation.metric_accuracy import get_our_metrics

        # roic_decimal=0.18 means pipeline raw_value = 18.0 (already in pct form)
        analysis = _make_analysis_with_roic(0.18)

        with patch("validation.metric_accuracy.get_cached_analysis") as mock_cached:
            mock_cached.return_value = analysis
            result = get_our_metrics("AAPL", "sqlite:///./test.db")

        assert result["roic_pct"] == 18.0

    def test_get_our_metrics_returns_empty_when_no_analysis(self):
        """Returns empty dict when no analysis is available."""
        from validation.metric_accuracy import get_our_metrics

        with (
            patch("validation.metric_accuracy.get_cached_analysis") as mock_cached,
            patch("validation.metric_accuracy.run_analysis_safe") as mock_run,
        ):
            mock_cached.return_value = None
            mock_run.return_value = None
            result = get_our_metrics("INVALID", "sqlite:///./test.db")

        assert result == {}

    def test_get_our_metrics_runs_fresh_when_not_cached(self):
        """Calls run_analysis_safe when ticker is not in DB."""
        from validation.metric_accuracy import get_our_metrics

        analysis = _make_analysis_with_roic(0.25)

        with (
            patch("validation.metric_accuracy.get_cached_analysis") as mock_cached,
            patch("validation.metric_accuracy.run_analysis_safe") as mock_run,
        ):
            mock_cached.return_value = None
            mock_run.return_value = analysis
            result = get_our_metrics("AAPL", "sqlite:///./test.db")

        mock_run.assert_called_once_with("AAPL")
        assert result["roic_pct"] == 25.0
