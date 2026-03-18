"""Tests for services/grader.py — letter grade assignment and aggregation."""

import pytest

from services.grader import (
    Grade,
    aggregate_grades,
    grade_metric,
    grade_to_score,
    numeric_to_grade,
)


class TestGradeMetric:
    def test_roe_excellent(self):
        assert grade_metric("roe", 0.40) == Grade.A_PLUS

    def test_roe_good(self):
        # 0.22 is between A_minus threshold (0.20) and A threshold (0.25), so A_minus
        assert grade_metric("roe", 0.22) == Grade.A_MINUS

    def test_roe_below_d_is_f(self):
        assert grade_metric("roe", -0.10) == Grade.F

    def test_none_returns_incomplete(self):
        assert grade_metric("roe", None) == Grade.INCOMPLETE

    def test_unknown_metric_returns_f(self):
        assert grade_metric("nonexistent_metric", 100.0) == Grade.F

    def test_lower_is_better_pe_cheap(self):
        # P/E of 7.0 is cheaper than the A+ cutoff of 8.0
        assert grade_metric("pe_ratio", 7.0) == Grade.A_PLUS

    def test_lower_is_better_pe_expensive(self):
        # P/E of 100 is worse than D cutoff
        assert grade_metric("pe_ratio", 100.0) == Grade.F

    def test_lower_is_better_pe_moderate(self):
        # P/E of 18-19 should be around B range
        g = grade_metric("pe_ratio", 18.5)
        assert g in (Grade.B, Grade.B_MINUS, Grade.A_MINUS)

    def test_net_debt_negative_is_best(self):
        # Net cash (negative net debt/EBITDA) should be A+
        assert grade_metric("net_debt_ebitda", -2.0) == Grade.A_PLUS

    def test_net_debt_high_is_bad(self):
        # Very high leverage
        g = grade_metric("net_debt_ebitda", 8.0)
        assert g == Grade.F

    def test_roic_thresholds(self):
        assert grade_metric("roic", 0.31) == Grade.A_PLUS
        assert grade_metric("roic", 0.23) == Grade.A
        assert grade_metric("roic", 0.11) == Grade.B_MINUS
        # 0.03 is below C_minus threshold (0.04) but above D (0.0), so D
        assert grade_metric("roic", 0.03) == Grade.D


class TestAggregateGrades:
    def test_empty_list_returns_incomplete(self):
        assert aggregate_grades([]) == Grade.INCOMPLETE

    def test_all_incomplete_returns_incomplete(self):
        result = aggregate_grades([Grade.INCOMPLETE, Grade.INCOMPLETE])
        assert result == Grade.INCOMPLETE

    def test_single_a_plus(self):
        result = aggregate_grades([Grade.A_PLUS])
        assert result == Grade.A_PLUS

    def test_average_a_and_b(self):
        # A (4.0) + B (3.0) = 3.5 average → A-
        result = aggregate_grades([Grade.A, Grade.B])
        assert result == Grade.A_MINUS

    def test_weighted_average(self):
        # A+ (4.3) weight 0.9 + F (0.0) weight 0.1 → ~3.87 → A
        result = aggregate_grades([Grade.A_PLUS, Grade.F], weights=[0.9, 0.1])
        assert result in (Grade.A, Grade.A_MINUS)

    def test_incomplete_excluded_from_average(self):
        # A+ and INC with equal weight — coverage is 50%
        # min_coverage defaults to 0.60, so 50% coverage → INCOMPLETE
        result = aggregate_grades([Grade.A_PLUS, Grade.INCOMPLETE])
        assert result == Grade.INCOMPLETE

    def test_incomplete_excluded_low_min_coverage(self):
        # With min_coverage=0.4, 50% coverage is enough
        result = aggregate_grades(
            [Grade.A_PLUS, Grade.INCOMPLETE], min_coverage=0.40
        )
        assert result == Grade.A_PLUS

    def test_mismatched_weights_raises(self):
        with pytest.raises(ValueError):
            aggregate_grades([Grade.A, Grade.B], weights=[1.0])


class TestGradeConversions:
    def test_a_plus_to_score(self):
        assert grade_to_score(Grade.A_PLUS) == 97

    def test_f_to_score(self):
        assert grade_to_score(Grade.F) == 30

    def test_incomplete_to_score(self):
        assert grade_to_score(Grade.INCOMPLETE) == 50

    def test_numeric_to_grade_roundtrip(self):
        for grade in [Grade.A_PLUS, Grade.A, Grade.B, Grade.C, Grade.D, Grade.F]:
            from services.grader import GRADE_NUMERIC
            numeric = GRADE_NUMERIC[grade]
            recovered = numeric_to_grade(numeric)
            # Recovered should be the same or adjacent grade
            assert abs(GRADE_NUMERIC[recovered] - numeric) <= 0.5
