"""Shared pytest fixtures for aEquity tests."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from models import MetricDrillDown

# ── DataFrame factories ────────────────────────────────────────────────────────

def make_income_stmt(**kwargs) -> pd.DataFrame:
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


def make_balance_sheet(**kwargs) -> pd.DataFrame:
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


def make_cashflow(**kwargs) -> pd.DataFrame:
    data = {
        "2024-09-30": {
            "Free Cash Flow": kwargs.get("fcf", 110_000),
        }
    }
    return pd.DataFrame(data)


# ── Ticker factory ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_ticker():
    """Return a factory for mock yfinance Ticker objects."""
    def _factory(**overrides):
        stock = MagicMock()
        stock.income_stmt = make_income_stmt(**overrides)
        stock.balance_sheet = make_balance_sheet(**overrides)
        stock.cashflow = make_cashflow(**overrides)
        stock.info = {
            "pegRatio": overrides.get("peg", 1.5),
            "priceToBook": overrides.get("pb", 2.0),
            "grossMargins": overrides.get("gross_margins", 0.40),
            "earningsGrowth": overrides.get("earnings_growth", 0.12),
            "heldPercentInsiders": overrides.get("insider_pct", 0.05),
            "dividendYield": overrides.get("dividend_yield", 0.02),
        }
        return stock
    return _factory


# ── Anthropic client mock ──────────────────────────────────────────────────────

@pytest.fixture
def mock_anthropic_client():
    """Return a factory for mock Anthropic clients with a canned text response."""
    def _factory(response_text: str) -> MagicMock:
        client = MagicMock()
        content_block = MagicMock()
        content_block.text = response_text
        client.messages.create.return_value.content = [content_block]
        return client
    return _factory


# ── MetricDrillDown factory ────────────────────────────────────────────────────

def make_metric(
    name: str = "Test Metric",
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
