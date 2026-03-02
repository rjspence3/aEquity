"""Tests for calculator functions using mocked yfinance responses."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tools.calculator_tools import (
    build_alignment_metrics,
    build_engine_metrics,
    build_fortress_metrics,
    calculate_current_ratio,
    calculate_earnings_growth_5yr,
    calculate_fcf_conversion,
    calculate_net_debt_ebitda,
    calculate_peg_ratio,
    calculate_price_to_book,
    calculate_roic,
)


def _make_income_stmt(**kwargs) -> pd.DataFrame:
    """Build a minimal mock income statement DataFrame."""
    data = {
        "2024-09-30": {
            "Operating Income": kwargs.get("operating_income", 100_000),
            "Tax Provision": kwargs.get("tax_provision", 25_000),
            "Pretax Income": kwargs.get("pretax_income", 125_000),
            "Net Income": kwargs.get("net_income", 100_000),
            "EBITDA": kwargs.get("ebitda", 150_000),
            "Depreciation And Amortization": kwargs.get("da", 50_000),
        }
    }
    return pd.DataFrame(data)


def _make_balance_sheet(**kwargs) -> pd.DataFrame:
    data = {
        "2024-09-30": {
            "Total Assets": kwargs.get("total_assets", 500_000),
            "Current Liabilities": kwargs.get("current_liabilities", 100_000),
            "Current Assets": kwargs.get("current_assets", 200_000),
            "Cash And Cash Equivalents": kwargs.get("cash", 50_000),
            "Total Debt": kwargs.get("total_debt", 80_000),
        }
    }
    return pd.DataFrame(data)


def _make_cashflow(**kwargs) -> pd.DataFrame:
    data = {
        "2024-09-30": {
            "Free Cash Flow": kwargs.get("fcf", 110_000),
        }
    }
    return pd.DataFrame(data)


@pytest.fixture
def mock_ticker():
    """Return a factory for mock yfinance Ticker objects."""
    def _factory(**overrides):
        ticker = MagicMock()
        ticker.income_stmt = _make_income_stmt(**overrides)
        ticker.balance_sheet = _make_balance_sheet(**overrides)
        ticker.cashflow = _make_cashflow(**overrides)
        ticker.info = {
            "pegRatio": overrides.get("peg", 1.5),
            "priceToBook": overrides.get("pb", 2.0),
            "grossMargins": overrides.get("gross_margins", 0.40),
            "earningsGrowth": overrides.get("earnings_growth", 0.12),
            "heldPercentInsiders": overrides.get("insider_pct", 0.05),
            "dividendYield": overrides.get("dividend_yield", 0.02),
            "buybackYield": None,
        }
        return ticker
    return _factory


class TestCalculateROIC:
    def test_normal_case(self, mock_ticker):
        ticker = mock_ticker()
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_roic("AAPL")
        assert result is not None
        # NOPAT = 100k * (1 - 25k/125k) = 80k
        # Invested Capital = 500k - 100k - 50k = 350k
        # ROIC = 80k / 350k ≈ 0.229
        assert pytest.approx(result, rel=0.01) == 80_000 / 350_000

    def test_zero_pretax_returns_none(self, mock_ticker):
        ticker = mock_ticker(pretax_income=0)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_roic("AAPL")
        assert result is None

    def test_negative_invested_capital_returns_none(self, mock_ticker):
        # total_assets - current_liabilities - cash = 100 - 200 - 50 = negative
        ticker = mock_ticker(total_assets=100, current_liabilities=200, cash=50)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_roic("AAPL")
        assert result is None

    def test_key_error_returns_none(self):
        ticker = MagicMock()
        ticker.income_stmt = pd.DataFrame()  # empty — will raise KeyError
        ticker.balance_sheet = pd.DataFrame()
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_roic("AAPL")
        assert result is None


class TestCalculateFCFConversion:
    def test_normal_case(self, mock_ticker):
        ticker = mock_ticker(fcf=120_000, net_income=100_000)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_fcf_conversion("AAPL")
        assert result is not None
        assert pytest.approx(result, rel=0.01) == 1.2

    def test_negative_net_income_returns_none(self, mock_ticker):
        ticker = mock_ticker(net_income=-10_000)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_fcf_conversion("AAPL")
        assert result is None


class TestCalculateNetDebtEBITDA:
    def test_normal_case(self, mock_ticker):
        ticker = mock_ticker(total_debt=80_000, cash=50_000, ebitda=150_000)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_net_debt_ebitda("AAPL")
        assert result is not None
        # (80k - 50k) / 150k = 0.2
        assert pytest.approx(result, rel=0.01) == 0.2

    def test_net_cash_returns_negative(self, mock_ticker):
        ticker = mock_ticker(total_debt=10_000, cash=50_000, ebitda=150_000)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_net_debt_ebitda("AAPL")
        assert result is not None
        assert result < 0


class TestCalculatePEGRatio:
    def test_returns_peg_from_info(self, mock_ticker):
        ticker = mock_ticker(peg=1.2)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_peg_ratio("AAPL")
        assert result == pytest.approx(1.2, rel=0.01)

    def test_none_peg_returns_none(self, mock_ticker):
        ticker = mock_ticker()
        ticker.info["pegRatio"] = None
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_peg_ratio("AAPL")
        assert result is None


class TestCalculatePriceToBk:
    def test_returns_value(self, mock_ticker):
        ticker = mock_ticker(pb=3.5)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_price_to_book("AAPL")
        assert result == pytest.approx(3.5, rel=0.01)


class TestCalculateCurrentRatio:
    def test_normal_case(self, mock_ticker):
        ticker = mock_ticker(current_assets=200_000, current_liabilities=100_000)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_current_ratio("AAPL")
        assert result == pytest.approx(2.0, rel=0.01)


class TestCalculateEarningsGrowth:
    def test_returns_growth(self, mock_ticker):
        ticker = mock_ticker(earnings_growth=0.15)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            result = calculate_earnings_growth_5yr("AAPL")
        assert result == pytest.approx(0.15, rel=0.01)


class TestBuildFortressMetrics:
    def test_returns_metrics_list(self, mock_ticker):
        ticker = mock_ticker()
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            metrics = build_fortress_metrics("AAPL")
        assert isinstance(metrics, list)
        assert len(metrics) > 0
        names = {m.metric_name for m in metrics}
        assert "ROIC" in names or "FCF Conversion" in names

    def test_scores_in_range(self, mock_ticker):
        ticker = mock_ticker()
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            metrics = build_fortress_metrics("AAPL")
        for m in metrics:
            assert 0 <= m.normalized_score <= 100


class TestBuildEngineMetrics:
    def test_returns_metrics_with_gross_margin(self, mock_ticker):
        ticker = mock_ticker(gross_margins=0.40)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            metrics = build_engine_metrics("AAPL")
        names = {m.metric_name for m in metrics}
        assert "Gross Margin" in names


class TestBuildAlignmentMetrics:
    def test_returns_insider_ownership(self, mock_ticker):
        ticker = mock_ticker(insider_pct=0.10)
        with patch("tools.calculator_tools.yf.Ticker", return_value=ticker):
            metrics = build_alignment_metrics("AAPL")
        names = {m.metric_name for m in metrics}
        assert "Insider Ownership" in names
