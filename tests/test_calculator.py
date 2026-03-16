"""Unit tests for calculator_tools normalization functions."""


from tools.calculator_tools import (
    normalize_current_ratio,
    normalize_debt_ratio,
    normalize_fcf_conversion,
    normalize_gross_margin,
    normalize_peg,
    normalize_price_to_book,
    normalize_roic,
)


class TestNormalizeROIC:
    def test_above_upper_bound_returns_100(self):
        assert normalize_roic(0.25) == 100

    def test_below_lower_bound_returns_0(self):
        assert normalize_roic(0.03) == 0

    def test_midpoint_is_roughly_50(self):
        score = normalize_roic(0.125)
        assert 45 <= score <= 55

    def test_boundary_at_5_percent(self):
        assert normalize_roic(0.05) == 0

    def test_boundary_at_20_percent(self):
        assert normalize_roic(0.20) == 100


class TestNormalizePEG:
    def test_zero_or_negative_returns_0(self):
        assert normalize_peg(0) == 0
        assert normalize_peg(-1.0) == 0

    def test_above_upper_bound_returns_0(self):
        assert normalize_peg(3.0) == 0

    def test_below_lower_bound_returns_100(self):
        assert normalize_peg(0.3) == 100

    def test_midpoint_roughly_50(self):
        score = normalize_peg(1.5)
        assert 45 <= score <= 55


class TestNormalizeDebtRatio:
    def test_negative_ratio_returns_100(self):
        assert normalize_debt_ratio(-1.0) == 100

    def test_above_4_returns_0(self):
        assert normalize_debt_ratio(5.0) == 0

    def test_below_1_returns_100(self):
        assert normalize_debt_ratio(0.5) == 100

    def test_midpoint(self):
        score = normalize_debt_ratio(2.5)
        assert 45 <= score <= 55


class TestNormalizeFCF:
    def test_high_conversion_returns_100(self):
        assert normalize_fcf_conversion(1.5) == 100

    def test_low_conversion_returns_0(self):
        assert normalize_fcf_conversion(0.3) == 0

    def test_midpoint(self):
        score = normalize_fcf_conversion(0.85)
        assert 45 <= score <= 55


class TestNormalizePB:
    def test_low_pb_returns_100(self):
        assert normalize_price_to_book(1.0) == 100

    def test_high_pb_returns_0(self):
        assert normalize_price_to_book(3.5) == 0

    def test_midpoint(self):
        score = normalize_price_to_book(2.25)
        assert 45 <= score <= 55


class TestNormalizeCurrentRatio:
    def test_high_cr_returns_100(self):
        assert normalize_current_ratio(3.0) == 100

    def test_low_cr_returns_0(self):
        assert normalize_current_ratio(0.5) == 0

    def test_cr_at_1_returns_0(self):
        assert normalize_current_ratio(1.0) == 0

    def test_cr_at_2_returns_100(self):
        assert normalize_current_ratio(2.0) == 100

    def test_midpoint(self):
        score = normalize_current_ratio(1.5)
        assert 45 <= score <= 55


class TestNormalizeGrossMargin:
    def test_at_60_percent_returns_100(self):
        assert normalize_gross_margin(0.60) == 100

    def test_above_60_percent_returns_100(self):
        assert normalize_gross_margin(0.85) == 100

    def test_just_below_60_percent_returns_75(self):
        assert normalize_gross_margin(0.59) == 75

    def test_at_40_percent_returns_75(self):
        assert normalize_gross_margin(0.40) == 75

    def test_just_below_40_percent_returns_50(self):
        assert normalize_gross_margin(0.39) == 50

    def test_at_25_percent_returns_50(self):
        assert normalize_gross_margin(0.25) == 50

    def test_just_below_25_percent_returns_25(self):
        assert normalize_gross_margin(0.24) == 25

    def test_at_10_percent_returns_25(self):
        assert normalize_gross_margin(0.10) == 25

    def test_just_below_10_percent_returns_0(self):
        assert normalize_gross_margin(0.09) == 0

    def test_zero_returns_0(self):
        assert normalize_gross_margin(0.0) == 0
