"""Tests for the 4 new guru framework modules."""

import pytest

from frameworks import run_new_frameworks
from frameworks.greenblatt import analyze_greenblatt
from frameworks.marks import analyze_marks
from frameworks.munger import analyze_munger
from frameworks.smith import analyze_smith
from services.grader import Grade


def _good_metrics() -> dict:
    """Metrics representing a high-quality business at a fair price."""
    return {
        "roic": 0.25,
        "roic_v2": 0.25,
        "operating_margin": 0.20,
        "current_ratio": 2.5,
        "earnings_yield": 0.07,
        "pe_ratio": 15.0,
        "debt_to_equity": 0.20,
        "gross_margin": 0.55,
        "fcf_conversion": 1.10,
    }


def _weak_metrics() -> dict:
    """Metrics representing a weak, overvalued, leveraged business."""
    return {
        "roic": 0.03,
        "roic_v2": 0.03,
        "operating_margin": 0.02,
        "current_ratio": 0.8,
        "earnings_yield": 0.01,
        "pe_ratio": 80.0,
        "debt_to_equity": 3.5,
        "gross_margin": 0.10,
        "fcf_conversion": 0.30,
    }


def _empty_metrics() -> dict:
    return {}


class TestMunger:
    def test_good_metrics_high_score(self):
        result = analyze_munger(_good_metrics())
        assert result["score"] >= 80
        assert result["grade"] in ("A+", "A", "A-")

    def test_weak_metrics_low_score(self):
        result = analyze_munger(_weak_metrics())
        # D grade = 55; weak metrics land around D
        assert result["score"] <= 60

    def test_empty_metrics_returns_incomplete(self):
        result = analyze_munger(_empty_metrics())
        assert result["grade"] == Grade.INCOMPLETE.value

    def test_result_has_required_keys(self):
        result = analyze_munger(_good_metrics())
        for key in ("grade", "score", "component_grades", "notes", "metrics_used", "metrics_required"):
            assert key in result

    def test_metrics_used_correct(self):
        result = analyze_munger(_good_metrics())
        assert result["metrics_used"] == 3
        assert result["metrics_required"] == 3


class TestGreenblatt:
    def test_good_magic_formula_high_score(self):
        result = analyze_greenblatt(_good_metrics())
        assert result["score"] >= 75

    def test_cheap_quality_company(self):
        metrics = {"earnings_yield": 0.12, "roic_v2": 0.30}
        result = analyze_greenblatt(metrics)
        assert result["grade"] in ("A+", "A", "A-")

    def test_expensive_low_quality(self):
        # earnings_yield=0.01 → D, roic_v2=0.04 → C_minus; aggregate ≈ C_minus (69)
        metrics = {"earnings_yield": 0.01, "roic_v2": 0.04}
        result = analyze_greenblatt(metrics)
        assert result["score"] <= 75

    def test_partial_metrics_still_grades(self):
        # Only earnings_yield available
        result = analyze_greenblatt({"earnings_yield": 0.08})
        # Should grade since coverage is 50% which is below 60% default
        assert result["grade"] == Grade.INCOMPLETE.value


class TestMarks:
    def test_fair_price_quality_business(self):
        result = analyze_marks(_good_metrics())
        assert result["score"] >= 75

    def test_overvalued_leveraged_business(self):
        result = analyze_marks(_weak_metrics())
        assert result["score"] <= 45

    def test_component_grades_populated(self):
        result = analyze_marks(_good_metrics())
        assert "pe_ratio" in result["component_grades"]
        assert "roic_v2" in result["component_grades"]
        assert "debt_to_equity" in result["component_grades"]


class TestSmith:
    def test_fundsmith_quality_passes(self):
        result = analyze_smith(_good_metrics())
        assert result["score"] >= 80
        assert not result.get("disqualified")

    def test_low_roic_disqualifies(self):
        metrics = {**_good_metrics(), "roic_v2": 0.10}  # below 15% floor
        result = analyze_smith(metrics)
        assert result["disqualified"]
        # Score should be capped at C-
        assert result["grade"] == "C-"

    def test_low_gross_margin_disqualifies(self):
        metrics = {**_good_metrics(), "gross_margin": 0.20}  # below 30% floor
        result = analyze_smith(metrics)
        assert result["disqualified"]
        assert result["grade"] == "C-"

    def test_high_quality_no_disqualification(self):
        metrics = {**_good_metrics(), "roic_v2": 0.25, "gross_margin": 0.60}
        result = analyze_smith(metrics)
        assert not result.get("disqualified")
        assert result["grade"] in ("A+", "A", "A-", "B+")

    def test_weak_business_f_grade(self):
        result = analyze_smith(_weak_metrics())
        # Disqualified; aggregate of D+C-+F+F ≈ D (score 55). D is not upgraded by disqualification
        assert result["score"] <= 60


class TestRunNewFrameworks:
    def test_returns_all_four_gurus(self):
        result = run_new_frameworks(_good_metrics())
        expected_names = {"Charlie Munger", "Joel Greenblatt", "Howard Marks", "Terry Smith"}
        assert set(result.keys()) == expected_names

    def test_all_results_have_required_keys(self):
        result = run_new_frameworks(_good_metrics())
        for name, fw_result in result.items():
            for key in ("grade", "score", "component_grades", "notes"):
                assert key in fw_result, f"{name} missing key: {key}"

    def test_score_range_valid(self):
        result = run_new_frameworks(_good_metrics())
        for fw_result in result.values():
            assert 0 <= fw_result["score"] <= 100
