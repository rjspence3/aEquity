"""Financial ratio calculations derived from yfinance data."""

import logging

import yfinance as yf

from models import MetricDrillDown

logger = logging.getLogger(__name__)


# ── Normalization helpers ──────────────────────────────────────────────────────

def normalize_roic(roic: float) -> int:
    """ROIC > 20% = 100, < 5% = 0, linear interpolation between."""
    return max(0, min(100, int((roic - 0.05) / 0.15 * 100)))


def normalize_peg(peg: float) -> int:
    """PEG < 0.5 = 100, > 2.5 = 0, linear interpolation between."""
    if peg <= 0:
        return 0
    return max(0, min(100, int((2.5 - peg) / 2.0 * 100)))


def normalize_debt_ratio(net_debt_ebitda: float) -> int:
    """NetDebt/EBITDA < 1 = 100, > 4 = 0, linear interpolation between."""
    if net_debt_ebitda < 0:
        return 100  # Net cash position is optimal
    return max(0, min(100, int((4 - net_debt_ebitda) / 3 * 100)))


def normalize_fcf_conversion(fcf_to_net_income: float) -> int:
    """FCF/NetIncome > 1.2 = 100, < 0.5 = 0, linear interpolation between."""
    return max(0, min(100, int((fcf_to_net_income - 0.5) / 0.7 * 100)))


def normalize_price_to_book(pb: float) -> int:
    """P/B < 1.5 = 100, > 3.0 = 0, linear interpolation between."""
    return max(0, min(100, int((3.0 - pb) / 1.5 * 100)))


def normalize_current_ratio(cr: float) -> int:
    """Current Ratio > 2.0 = 100, < 1.0 = 0, linear interpolation between."""
    return max(0, min(100, int((cr - 1.0) / 1.0 * 100)))


def normalize_gross_margin(gross_margin: float) -> int:
    """
    Gross margin → 0-100 score using domain-aware thresholds.

    60%+ = 100 (software/luxury), 40-59% = 75 (consumer brands),
    25-39% = 50 (industrial/healthcare), 10-24% = 25 (retail/distribution), <10% = 0.
    """
    if gross_margin >= 0.60:
        return 100
    if gross_margin >= 0.40:
        return 75
    if gross_margin >= 0.25:
        return 50
    if gross_margin >= 0.10:
        return 25
    return 0


# ── Raw calculation functions ──────────────────────────────────────────────────
#
# All functions accept a pre-fetched yf.Ticker object rather than a ticker
# string, so callers (primarily pipeline.analyze_ticker) can create one Ticker
# instance and share it across all calculations without redundant HTTP fetches.

def calculate_roic(stock: yf.Ticker) -> float | None:
    """
    ROIC = NOPAT / Invested Capital.

    Returns decimal (e.g., 0.18 for 18%) or None if data unavailable.
    """
    income = stock.income_stmt
    balance = stock.balance_sheet

    try:
        operating_income = float(income.loc["Operating Income"].iloc[0])
        tax_provision = float(income.loc["Tax Provision"].iloc[0])
        pretax_income = float(income.loc["Pretax Income"].iloc[0])

        if pretax_income == 0:
            return None

        tax_rate = tax_provision / pretax_income
        nopat = operating_income * (1 - tax_rate)

        total_assets = float(balance.loc["Total Assets"].iloc[0])
        current_liabilities = float(balance.loc["Current Liabilities"].iloc[0])
        cash = float(balance.loc["Cash And Cash Equivalents"].iloc[0])
        invested_capital = total_assets - current_liabilities - cash

        if invested_capital <= 0:
            return None

        return nopat / invested_capital

    except (KeyError, IndexError, ZeroDivisionError, ValueError) as exc:
        logger.debug("ROIC calculation failed: %s", exc)
        return None


def calculate_fcf_conversion(stock: yf.Ticker) -> float | None:
    """
    FCF Conversion = Free Cash Flow / Net Income.

    Returns ratio or None if unavailable.
    """
    cashflow = stock.cashflow
    income = stock.income_stmt

    try:
        fcf = float(cashflow.loc["Free Cash Flow"].iloc[0])
        net_income = float(income.loc["Net Income"].iloc[0])

        if net_income <= 0:
            return None

        return fcf / net_income

    except (KeyError, IndexError, ZeroDivisionError, ValueError) as exc:
        logger.debug("FCF conversion failed: %s", exc)
        return None


def calculate_net_debt_ebitda(stock: yf.Ticker) -> float | None:
    """
    Net Debt / EBITDA ratio.

    Returns ratio (negative = net cash) or None if unavailable.
    """
    balance = stock.balance_sheet
    income = stock.income_stmt

    try:
        total_debt = 0.0
        for label in ["Total Debt", "Long Term Debt", "Short Long Term Debt"]:
            if label in balance.index:
                total_debt = float(balance.loc[label].iloc[0])
                break

        cash = float(balance.loc["Cash And Cash Equivalents"].iloc[0])
        net_debt = total_debt - cash

        ebitda = float(income.loc["EBITDA"].iloc[0]) if "EBITDA" in income.index else None
        if ebitda is None:
            # Derive EBITDA = Operating Income + D&A
            operating_income = float(income.loc["Operating Income"].iloc[0])
            da = 0.0
            if "Depreciation And Amortization" in income.index:
                da = float(income.loc["Depreciation And Amortization"].iloc[0])
            elif "Reconciled Depreciation" in income.index:
                da = float(income.loc["Reconciled Depreciation"].iloc[0])
            ebitda = operating_income + da

        if ebitda <= 0:
            return None

        return net_debt / ebitda

    except (KeyError, IndexError, ZeroDivisionError, ValueError) as exc:
        logger.debug("Net Debt/EBITDA failed: %s", exc)
        return None


def calculate_peg_ratio(stock: yf.Ticker) -> float | None:
    """
    PEG Ratio from yfinance info dict.

    Returns ratio or None.
    """
    try:
        peg = stock.info.get("pegRatio")
        return float(peg) if peg is not None else None
    except Exception as exc:
        logger.debug("PEG ratio failed: %s", exc)
        return None


def calculate_price_to_book(stock: yf.Ticker) -> float | None:
    """P/B ratio from yfinance info."""
    try:
        pb = stock.info.get("priceToBook")
        return float(pb) if pb is not None else None
    except Exception as exc:
        logger.debug("P/B ratio failed: %s", exc)
        return None


def calculate_current_ratio(stock: yf.Ticker) -> float | None:
    """Current ratio from yfinance balance sheet."""
    balance = stock.balance_sheet

    try:
        current_assets = float(balance.loc["Current Assets"].iloc[0])
        current_liabilities = float(balance.loc["Current Liabilities"].iloc[0])

        if current_liabilities <= 0:
            return None

        return current_assets / current_liabilities

    except (KeyError, IndexError, ZeroDivisionError, ValueError) as exc:
        logger.debug("Current ratio failed: %s", exc)
        return None


def calculate_trailing_earnings_growth(stock: yf.Ticker) -> float | None:
    """
    Trailing earnings growth from yfinance info (earningsGrowth field, TTM).

    Note: this is trailing 12-month growth, NOT a 5-year CAGR.
    TODO: compute true 5yr CAGR by comparing historical EPS across annual income statements.
    Falls back to revenueGrowth if earningsGrowth is unavailable.
    """
    try:
        info = stock.info
        growth = info.get("earningsGrowth") or info.get("revenueGrowth")
        return float(growth) if growth is not None else None
    except Exception as exc:
        logger.debug("Earnings growth failed: %s", exc)
        return None


# ── Pillar metric builders ─────────────────────────────────────────────────────

def build_fortress_metrics(stock: yf.Ticker) -> list[MetricDrillDown]:
    """Build The Fortress pillar (financial health) metrics."""
    metrics = []

    roic = calculate_roic(stock)
    if roic is not None:
        metrics.append(MetricDrillDown(
            metric_name="ROIC",
            raw_value=round(roic * 100, 2),
            normalized_score=normalize_roic(roic),
            source="calculated",
            evidence=f"ROIC = {roic * 100:.1f}% (yfinance income_stmt + balance_sheet)",
            confidence="high",
        ))

    fcf = calculate_fcf_conversion(stock)
    if fcf is not None:
        metrics.append(MetricDrillDown(
            metric_name="FCF Conversion",
            raw_value=round(fcf, 3),
            normalized_score=normalize_fcf_conversion(fcf),
            source="calculated",
            evidence=f"FCF / Net Income = {fcf:.2f}x (from yfinance cashflow)",
            confidence="high",
        ))

    nd_ebitda = calculate_net_debt_ebitda(stock)
    if nd_ebitda is not None:
        metrics.append(MetricDrillDown(
            metric_name="Net Debt / EBITDA",
            raw_value=round(nd_ebitda, 2),
            normalized_score=normalize_debt_ratio(nd_ebitda),
            source="calculated",
            evidence=f"Net Debt / EBITDA = {nd_ebitda:.2f}x (from yfinance balance_sheet)",
            confidence="high",
        ))

    return metrics


def build_engine_metrics(stock: yf.Ticker) -> list[MetricDrillDown]:
    """Build The Engine pillar (business quality) metrics."""
    metrics = []

    roic = calculate_roic(stock)
    if roic is not None:
        metrics.append(MetricDrillDown(
            metric_name="ROIC",
            raw_value=round(roic * 100, 2),
            normalized_score=normalize_roic(roic),
            source="calculated",
            evidence=f"ROIC = {roic * 100:.1f}% — core quality signal",
            confidence="high",
        ))

    try:
        gross_margins = stock.info.get("grossMargins")
        if gross_margins is not None:
            score = normalize_gross_margin(float(gross_margins))
            metrics.append(MetricDrillDown(
                metric_name="Gross Margin",
                raw_value=round(float(gross_margins) * 100, 2),
                normalized_score=score,
                source="yfinance",
                evidence=f"Gross margin = {float(gross_margins) * 100:.1f}%",
                confidence="high",
            ))
    except Exception as exc:
        logger.debug("Gross margin failed: %s", exc)

    return metrics


def build_alignment_metrics(stock: yf.Ticker) -> list[MetricDrillDown]:
    """Build the Alignment pillar (governance) metrics."""
    metrics = []

    try:
        info = stock.info

        insider_pct = info.get("heldPercentInsiders")
        if insider_pct is not None:
            score = max(0, min(100, int(float(insider_pct) * 200)))  # 50% = 100
            metrics.append(MetricDrillDown(
                metric_name="Insider Ownership",
                raw_value=round(float(insider_pct) * 100, 2),
                normalized_score=score,
                source="yfinance",
                evidence=f"Insiders hold {float(insider_pct) * 100:.1f}% of shares",
                confidence="medium",
            ))

        dividend_yield = float(info.get("dividendYield") or 0.0)
        # yfinance does not provide buyback yield directly; shareholder yield is dividend-only.
        # TODO: derive buyback yield from repurchaseOfStock in the cashflow statement.
        shareholder_yield = dividend_yield
        if shareholder_yield > 0:
            score = max(0, min(100, int(shareholder_yield * 1000)))
            metrics.append(MetricDrillDown(
                metric_name="Shareholder Yield",
                raw_value=round(shareholder_yield * 100, 2),
                normalized_score=score,
                source="yfinance",
                evidence=f"Dividend yield = {shareholder_yield * 100:.2f}% (buyback yield unavailable from yfinance)",
                confidence="medium",
            ))

    except Exception as exc:
        logger.debug("Alignment metrics failed: %s", exc)

    return metrics
