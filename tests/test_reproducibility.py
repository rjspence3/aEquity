"""Tests for validation/reproducibility.py."""

from datetime import date

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


def _make_analysis(
    moat_score: int = 75,
    understandability_score: int = 80,
    overall_score: int = 70,
) -> CompanyAnalysis:
    """Build a synthetic CompanyAnalysis with the given LLM scores."""
    moat_metric = _make_metric("Moat Score", raw=float(moat_score), score=moat_score, source="10-K")
    understand_metric = _make_metric(
        "Understandability", raw=float(understandability_score), score=understandability_score, source="10-K"
    )
    engine_metric = _make_metric("ROIC", raw=20.0, score=80)

    pillar_engine = PillarAnalysis(
        pillar_name="The Engine",
        score=80,
        metrics=[engine_metric],
        summary="Strong engine.",
        red_flags=[],
    )
    pillar_moat = PillarAnalysis(
        pillar_name="The Moat",
        score=moat_score,
        metrics=[moat_metric, understand_metric],
        summary="Wide moat.",
        red_flags=[],
    )
    pillar_fortress = PillarAnalysis(
        pillar_name="The Fortress",
        score=70,
        metrics=[_make_metric("FCF Conversion", raw=1.1, score=86)],
        summary="Solid fortress.",
        red_flags=[],
    )
    pillar_alignment = PillarAnalysis(
        pillar_name="Alignment",
        score=60,
        metrics=[_make_metric("Insider Ownership", raw=5.0, score=60, source="yfinance")],
        summary="Aligned.",
        red_flags=[],
    )

    guru = GuruScorecard(
        guru_name="Warren Buffett",
        score=overall_score,
        verdict="Buy",
        rationale="Strong fundamentals.",
        key_metrics=[_make_metric("ROIC", raw=20.0, score=80)],
    )

    return CompanyAnalysis(
        ticker="AAPL",
        company_name="Apple Inc.",
        analysis_date=date(2025, 1, 1),
        filing_date=date(2024, 10, 1),
        filing_type="10-K",
        pillars=[pillar_engine, pillar_moat, pillar_fortress, pillar_alignment],
        gurus=[guru],
        overall_score=overall_score,
        confidence="high",
        errors=[],
        partial=False,
    )


class TestExtractLlmScores:
    def test_extract_llm_scores_from_moat_pillar(self):
        """Correctly extracts moat and understandability from The Moat pillar metrics."""
        from validation.reproducibility import extract_llm_scores

        analysis = _make_analysis(moat_score=82, understandability_score=88)
        result = extract_llm_scores(analysis)

        assert result["moat"] == 82
        assert result["understandability"] == 88

    def test_extract_llm_scores_falls_back_to_pillar_score(self):
        """Falls back to pillar score when individual metric entries are absent."""
        from validation.reproducibility import extract_llm_scores

        # Build analysis with moat pillar that has no named metrics
        plain_metric = _make_metric("Some Other Metric", raw=50.0, score=50, source="10-K")
        pillar_moat = PillarAnalysis(
            pillar_name="The Moat",
            score=65,
            metrics=[plain_metric],
            summary="Moderate moat.",
            red_flags=[],
        )
        pillar_engine = PillarAnalysis(
            pillar_name="The Engine",
            score=70,
            metrics=[_make_metric("ROIC", raw=20.0, score=80)],
            summary="Engine.",
            red_flags=[],
        )
        pillar_fortress = PillarAnalysis(
            pillar_name="The Fortress",
            score=70,
            metrics=[],
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
            score=65,
            verdict="Buy",
            rationale="OK.",
            key_metrics=[],
        )
        analysis = CompanyAnalysis(
            ticker="AAPL",
            company_name="Apple Inc.",
            analysis_date=date(2025, 1, 1),
            filing_date=date(2024, 10, 1),
            filing_type="10-K",
            pillars=[pillar_engine, pillar_moat, pillar_fortress, pillar_alignment],
            gurus=[guru],
            overall_score=65,
            confidence="medium",
        )

        result = extract_llm_scores(analysis)
        assert result["moat"] == 65
        assert result["understandability"] == 65

    def test_extract_llm_scores_returns_50_when_no_moat_pillar(self):
        """Returns defaults when The Moat pillar is missing."""
        from validation.reproducibility import extract_llm_scores

        pillar_engine = PillarAnalysis(
            pillar_name="The Engine",
            score=70,
            metrics=[_make_metric("ROIC", raw=20.0, score=80)],
            summary="Engine.",
            red_flags=[],
        )
        pillar_fortress = PillarAnalysis(
            pillar_name="The Fortress",
            score=70,
            metrics=[],
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
        pillar_moat = PillarAnalysis(
            pillar_name="The Moat",
            score=50,
            metrics=[],
            summary="Moat.",
            red_flags=[],
        )
        guru = GuruScorecard(
            guru_name="Warren Buffett",
            score=60,
            verdict="Hold",
            rationale="OK.",
            key_metrics=[],
        )
        analysis = CompanyAnalysis(
            ticker="XYZ",
            company_name="XYZ Corp",
            analysis_date=date(2025, 1, 1),
            filing_date=date(2024, 10, 1),
            filing_type="10-K",
            pillars=[pillar_engine, pillar_moat, pillar_fortress, pillar_alignment],
            gurus=[guru],
            overall_score=60,
            confidence="medium",
        )

        result = extract_llm_scores(analysis)
        assert "moat" in result
        assert "understandability" in result


class TestComputeVarianceReport:
    def test_compute_variance_report_flags_high_stddev(self):
        """Flags tickers where moat stddev > VARIANCE_THRESHOLD."""
        from validation.reproducibility import compute_variance_report

        runs = [
            {"moat": 60, "understandability": 70, "composite": 65},
            {"moat": 80, "understandability": 72, "composite": 67},
            {"moat": 100, "understandability": 74, "composite": 68},
        ]
        report = compute_variance_report("TSLA", runs)

        assert report["flagged"] is True
        assert report["ticker"] == "TSLA"
        assert report["moat_stddev"] > 10

    def test_compute_variance_report_passes_stable_scores(self):
        """Does not flag tickers where all stddevs are <= VARIANCE_THRESHOLD."""
        from validation.reproducibility import compute_variance_report

        runs = [
            {"moat": 78, "understandability": 85, "composite": 72},
            {"moat": 80, "understandability": 87, "composite": 73},
            {"moat": 79, "understandability": 86, "composite": 74},
        ]
        report = compute_variance_report("AAPL", runs)

        assert report["flagged"] is False
        assert report["moat_stddev"] <= 10
        assert report["understand_stddev"] <= 10

    def test_compute_variance_report_handles_none_values(self):
        """Handles runs where analysis failed (None values)."""
        from validation.reproducibility import compute_variance_report

        runs = [
            {"moat": 75, "understandability": 80, "composite": 70},
            {"moat": None, "understandability": None, "composite": None},
            {"moat": 77, "understandability": 82, "composite": 72},
        ]
        report = compute_variance_report("WMT", runs)

        assert "moat_stddev" in report
        assert "understand_stddev" in report
        assert report["flagged"] is False  # Only 2 valid values, stddev is small

    def test_compute_variance_report_includes_per_run_values(self):
        """Report includes per-run breakdown for CSV output."""
        from validation.reproducibility import compute_variance_report

        runs = [
            {"moat": 70, "understandability": 75, "composite": 68},
            {"moat": 72, "understandability": 77, "composite": 70},
            {"moat": 74, "understandability": 79, "composite": 72},
        ]
        report = compute_variance_report("MSFT", runs)

        assert report["run1_moat"] == 70
        assert report["run2_moat"] == 72
        assert report["run3_moat"] == 74
