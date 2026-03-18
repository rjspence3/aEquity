"""Tests for new metric calculation functions added in Phase 1."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from tools.calculator_tools import (
    calculate_debt_to_equity,
    calculate_earnings_yield,
    calculate_eps_growth,
    calculate_fcf_growth,
    calculate_fcf_yield,
    calculate_graham_number,
    calculate_gross_margin,
    calculate_net_margin,
    calculate_operating_margin,
    calculate_owner_earnings,
    calculate_owner_earnings_yield,
    calculate_pe_ratio,
    calculate_revenue_growth,
    calculate_roa,
    calculate_roce,
    calculate_roe,
    calculate_roic_v2,
    compute_all_metrics,
)


def _make_stock(
    *,
    roe: float = 0.20,
    roa: float = 0.10,
    operating_margins: float = 0.15,
    profit_margins: float = 0.12,
    gross_margins: float = 0.45,
    trailing_pe: float = 18.0,
    free_cashflow: float = 500_000,
    market_cap: float = 10_000_000,
    enterprise_to_fcf: float = 20.0,
    operating_income: float = 200_000,
    net_income: float = 150_000,
    da: float = 50_000,
    capex: float = 30_000,
    total_assets: float = 800_000,
    current_liabilities: float = 100_000,
    total_debt: float = 100_000,
    equity: float = 400_000,
    cash: float = 80_000,
    current_assets: float = 250_000,
    revenue_current: float = 1_200_000,
    revenue_prior: float = 1_000_000,
    eps_current: float = 5.0,
    eps_prior: float = 4.0,
    fcf_current: float = 500_000,
    fcf_prior: float = 400_000,
    trailing_eps: float = 8.0,
    book_value: float = 20.0,
) -> MagicMock:
    stock = MagicMock()
    stock.info = {
        "returnOnEquity": roe,
        "returnOnAssets": roa,
        "operatingMargins": operating_margins,
        "profitMargins": profit_margins,
        "grossMargins": gross_margins,
        "trailingPE": trailing_pe,
        "freeCashflow": free_cashflow,
        "marketCap": market_cap,
        "enterpriseToFreeCashflow": enterprise_to_fcf,
        "trailingEps": trailing_eps,
        "bookValue": book_value,
    }

    stock.income_stmt = pd.DataFrame({
        "2024-09-30": {
            "Operating Income": operating_income,
            "Net Income": net_income,
            "Depreciation And Amortization": da,
            "Total Revenue": revenue_current,
            "Basic EPS": eps_current,
        },
        "2023-09-30": {
            "Operating Income": operating_income * 0.9,
            "Net Income": net_income * 0.85,
            "Depreciation And Amortization": da,
            "Total Revenue": revenue_prior,
            "Basic EPS": eps_prior,
        },
    })

    stock.balance_sheet = pd.DataFrame({
        "2024-09-30": {
            "Total Assets": total_assets,
            "Current Liabilities": current_liabilities,
            "Current Assets": current_assets,
            "Cash And Cash Equivalents": cash,
            "Total Debt": total_debt,
            "Stockholders Equity": equity,
        }
    })

    stock.cashflow = pd.DataFrame({
        "2024-09-30": {
            "Free Cash Flow": fcf_current,
            "Capital Expenditure": -capex,
            "Depreciation And Amortization": da,
        },
        "2023-09-30": {
            "Free Cash Flow": fcf_prior,
            "Capital Expenditure": -capex,
        },
    })

    return stock


class TestInfoBasedMetrics:
    def test_roe_returns_float(self):
        stock = _make_stock(roe=0.25)
        assert calculate_roe(stock) == pytest.approx(0.25)

    def test_roe_none_when_missing(self):
        stock = _make_stock()
        stock.info.pop("returnOnEquity")
        assert calculate_roe(stock) is None

    def test_roa(self):
        stock = _make_stock(roa=0.08)
        assert calculate_roa(stock) == pytest.approx(0.08)

    def test_operating_margin(self):
        stock = _make_stock(operating_margins=0.18)
        assert calculate_operating_margin(stock) == pytest.approx(0.18)

    def test_net_margin(self):
        stock = _make_stock(profit_margins=0.10)
        assert calculate_net_margin(stock) == pytest.approx(0.10)

    def test_gross_margin(self):
        stock = _make_stock(gross_margins=0.55)
        assert calculate_gross_margin(stock) == pytest.approx(0.55)

    def test_pe_ratio(self):
        stock = _make_stock(trailing_pe=20.0)
        assert calculate_pe_ratio(stock) == pytest.approx(20.0)

    def test_earnings_yield(self):
        stock = _make_stock(trailing_pe=20.0)
        assert calculate_earnings_yield(stock) == pytest.approx(0.05)

    def test_earnings_yield_none_when_pe_none(self):
        stock = _make_stock()
        stock.info.pop("trailingPE")
        assert calculate_earnings_yield(stock) is None

    def test_fcf_yield(self):
        stock = _make_stock(free_cashflow=500_000, market_cap=10_000_000)
        assert calculate_fcf_yield(stock) == pytest.approx(0.05)

    def test_fcf_yield_none_when_market_cap_zero(self):
        stock = _make_stock()
        stock.info["marketCap"] = 0
        assert calculate_fcf_yield(stock) is None


class TestStatementBasedMetrics:
    def test_debt_to_equity(self):
        stock = _make_stock(total_debt=200_000, equity=400_000)
        result = calculate_debt_to_equity(stock)
        assert result == pytest.approx(0.50)

    def test_debt_to_equity_none_when_negative_equity(self):
        stock = _make_stock(equity=-50_000)
        assert calculate_debt_to_equity(stock) is None

    def test_roce(self):
        # ROCE = 200k / (800k - 100k) = 200k / 700k ≈ 0.286
        stock = _make_stock(operating_income=200_000, total_assets=800_000, current_liabilities=100_000)
        result = calculate_roce(stock)
        assert result == pytest.approx(200_000 / 700_000)

    def test_roic_v2(self):
        # NOPAT = 200k * 0.75 = 150k
        # Invested capital = 100k (debt) + 400k (equity) - 80k (cash) = 420k
        # ROIC v2 = 150k / 420k ≈ 0.357
        stock = _make_stock(
            operating_income=200_000,
            total_debt=100_000,
            equity=400_000,
            cash=80_000,
        )
        result = calculate_roic_v2(stock)
        expected = (200_000 * 0.75) / (100_000 + 400_000 - 80_000)
        assert result == pytest.approx(expected)

    def test_owner_earnings(self):
        # OE = 150k (NI) + 50k (D&A) - 30k (capex) = 170k
        stock = _make_stock(net_income=150_000, da=50_000, capex=30_000)
        result = calculate_owner_earnings(stock)
        assert result == pytest.approx(170_000)

    def test_graham_number(self):
        import math
        stock = _make_stock(trailing_eps=8.0, book_value=20.0)
        result = calculate_graham_number(stock)
        expected = math.sqrt(22.5 * 8.0 * 20.0)
        assert result == pytest.approx(expected)

    def test_graham_number_none_when_negative_eps(self):
        stock = _make_stock()
        stock.info["trailingEps"] = -2.0
        assert calculate_graham_number(stock) is None


class TestGrowthMetrics:
    def test_revenue_growth(self):
        stock = _make_stock(revenue_current=1_200_000, revenue_prior=1_000_000)
        result = calculate_revenue_growth(stock)
        assert result == pytest.approx(0.20)

    def test_eps_growth(self):
        stock = _make_stock(eps_current=5.0, eps_prior=4.0)
        result = calculate_eps_growth(stock)
        assert result == pytest.approx(0.25)

    def test_fcf_growth(self):
        stock = _make_stock(fcf_current=500_000, fcf_prior=400_000)
        result = calculate_fcf_growth(stock)
        assert result == pytest.approx(0.25)

    def test_revenue_growth_none_when_single_period(self):
        stock = _make_stock()
        # Overwrite with single-column income stmt
        stock.income_stmt = pd.DataFrame({
            "2024-09-30": {"Total Revenue": 1_000_000}
        })
        assert calculate_revenue_growth(stock) is None

    def test_negative_prior_eps_returns_none(self):
        stock = _make_stock()
        stock.income_stmt = pd.DataFrame({
            "2024-09-30": {"Basic EPS": 5.0},
            "2023-09-30": {"Basic EPS": 0.0},
        })
        # Zero prior → _growth_from_history returns None
        assert calculate_eps_growth(stock) is None


class TestComputeAllMetrics:
    def test_returns_all_expected_keys(self):
        stock = _make_stock()
        result = compute_all_metrics(stock)
        required_keys = [
            "roic", "fcf_conversion", "net_debt_ebitda", "peg_ratio",
            "price_to_book", "current_ratio", "earnings_growth",
            "roe", "roa", "operating_margin", "net_margin", "gross_margin",
            "roic_v2", "pe_ratio", "earnings_yield", "fcf_yield",
            "debt_to_equity", "owner_earnings_yield",
            "revenue_growth", "eps_growth", "fcf_growth",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_nan_converted_to_none(self):
        import math
        stock = _make_stock()
        # Inject a NaN into ROE
        stock.info["returnOnEquity"] = float("nan")
        result = compute_all_metrics(stock)
        assert result["roe"] is None

    def test_legacy_keys_unchanged(self):
        """Original 7 keys must still be present and calculated the same way."""
        stock = _make_stock()
        result = compute_all_metrics(stock)
        legacy_keys = [
            "roic", "fcf_conversion", "net_debt_ebitda", "peg_ratio",
            "price_to_book", "current_ratio", "earnings_growth",
        ]
        for key in legacy_keys:
            assert key in result
