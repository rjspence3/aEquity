"""Financial ratio calculations derived from yfinance data."""

import logging

import yfinance as yf

from models import MetricDrillDown
from scoring_config import (
    CURRENT_RATIO_LOWER,
    CURRENT_RATIO_UPPER,
    DEBT_LOWER,
    DEBT_UPPER,
    FCF_LOWER,
    FCF_UPPER,
    GROSS_MARGIN_TIER_HIGH,
    GROSS_MARGIN_TIER_LOW,
    GROSS_MARGIN_TIER_MID,
    GROSS_MARGIN_TIER_MID_HIGH,
    PB_LOWER,
    PB_UPPER,
    PEG_LOWER,
    PEG_UPPER,
    ROIC_LOWER,
    ROIC_UPPER,
)

logger = logging.getLogger(__name__)


# ── Normalization helpers ──────────────────────────────────────────────────────

def normalize_roic(roic: float) -> int:
    """ROIC >= ROIC_UPPER = 100, <= ROIC_LOWER = 0, linear interpolation between."""
    return max(0, min(100, int((roic - ROIC_LOWER) / (ROIC_UPPER - ROIC_LOWER) * 100)))


def normalize_peg(peg: float) -> int:
    """PEG <= PEG_LOWER = 100, >= PEG_UPPER = 0, linear interpolation between."""
    if peg <= 0:
        return 0
    return max(0, min(100, int((PEG_UPPER - peg) / (PEG_UPPER - PEG_LOWER) * 100)))


def normalize_debt_ratio(net_debt_ebitda: float) -> int:
    """NetDebt/EBITDA <= DEBT_LOWER = 100, >= DEBT_UPPER = 0, linear interpolation between."""
    if net_debt_ebitda < 0:
        return 100  # Net cash position is optimal
    return max(0, min(100, int((DEBT_UPPER - net_debt_ebitda) / (DEBT_UPPER - DEBT_LOWER) * 100)))


def normalize_fcf_conversion(fcf_to_net_income: float) -> int:
    """FCF/NetIncome >= FCF_UPPER = 100, <= FCF_LOWER = 0, linear interpolation between."""
    return max(0, min(100, int((fcf_to_net_income - FCF_LOWER) / (FCF_UPPER - FCF_LOWER) * 100)))


def normalize_price_to_book(pb: float) -> int:
    """P/B <= PB_LOWER = 100, >= PB_UPPER = 0, linear interpolation between."""
    return max(0, min(100, int((PB_UPPER - pb) / (PB_UPPER - PB_LOWER) * 100)))


def normalize_current_ratio(cr: float) -> int:
    """Current Ratio >= CURRENT_RATIO_UPPER = 100, <= CURRENT_RATIO_LOWER = 0."""
    return max(
        0,
        min(
            100,
            int((cr - CURRENT_RATIO_LOWER) / (CURRENT_RATIO_UPPER - CURRENT_RATIO_LOWER) * 100),
        ),
    )


def normalize_gross_margin(gross_margin: float) -> int:
    """
    Gross margin → 0-100 score using domain-aware thresholds.

    Tiers defined in scoring_config: HIGH (software/luxury) → 100,
    MID_HIGH (consumer brands) → 75, MID (industrial/healthcare) → 50,
    LOW (retail/distribution) → 25, below LOW → 0.
    """
    if gross_margin >= GROSS_MARGIN_TIER_HIGH:
        return 100
    if gross_margin >= GROSS_MARGIN_TIER_MID_HIGH:
        return 75
    if gross_margin >= GROSS_MARGIN_TIER_MID:
        return 50
    if gross_margin >= GROSS_MARGIN_TIER_LOW:
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
    Falls back to revenueGrowth if earningsGrowth is unavailable.
    """
    try:
        info = stock.info
        growth = info.get("earningsGrowth") or info.get("revenueGrowth")
        return float(growth) if growth is not None else None
    except Exception as exc:
        logger.debug("Earnings growth failed: %s", exc)
        return None


# ── Additional raw metric functions ───────────────────────────────────────────

def calculate_roe(stock: yf.Ticker) -> float | None:
    """Return on Equity from yfinance info. Returns decimal (0.20 = 20%)."""
    try:
        val = stock.info.get("returnOnEquity")
        return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("ROE failed: %s", exc)
        return None


def calculate_roa(stock: yf.Ticker) -> float | None:
    """Return on Assets from yfinance info. Returns decimal."""
    try:
        val = stock.info.get("returnOnAssets")
        return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("ROA failed: %s", exc)
        return None


def calculate_operating_margin(stock: yf.Ticker) -> float | None:
    """Operating margin from yfinance info. Returns decimal."""
    try:
        val = stock.info.get("operatingMargins")
        return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("Operating margin failed: %s", exc)
        return None


def calculate_net_margin(stock: yf.Ticker) -> float | None:
    """Net profit margin from yfinance info. Returns decimal."""
    try:
        val = stock.info.get("profitMargins")
        return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("Net margin failed: %s", exc)
        return None


def calculate_gross_margin(stock: yf.Ticker) -> float | None:
    """Gross margin from yfinance info. Returns decimal."""
    try:
        val = stock.info.get("grossMargins")
        return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("Gross margin failed: %s", exc)
        return None


def calculate_pe_ratio(stock: yf.Ticker) -> float | None:
    """Trailing P/E ratio from yfinance info."""
    try:
        val = stock.info.get("trailingPE")
        return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("P/E ratio failed: %s", exc)
        return None


def calculate_earnings_yield(stock: yf.Ticker) -> float | None:
    """Earnings yield = 1 / P/E. Returns decimal (0.05 = 5%)."""
    pe = calculate_pe_ratio(stock)
    if pe is not None and pe > 0:
        return 1.0 / pe
    return None


def calculate_fcf_yield(stock: yf.Ticker) -> float | None:
    """FCF yield = Free Cash Flow / Market Cap. Returns decimal."""
    try:
        info = stock.info
        fcf = info.get("freeCashflow")
        market_cap = info.get("marketCap")
        if fcf is not None and market_cap and market_cap > 0:
            return float(fcf) / float(market_cap)
        return None
    except Exception as exc:
        logger.debug("FCF yield failed: %s", exc)
        return None


def calculate_ev_fcf(stock: yf.Ticker) -> float | None:
    """EV / FCF multiple from yfinance info."""
    try:
        val = stock.info.get("enterpriseToFreeCashflow")
        return float(val) if val is not None else None
    except Exception as exc:
        logger.debug("EV/FCF failed: %s", exc)
        return None


def calculate_debt_to_equity(stock: yf.Ticker) -> float | None:
    """Debt-to-equity ratio computed from balance sheet. Returns decimal ratio."""
    balance = stock.balance_sheet
    try:
        total_debt = 0.0
        for label in ["Total Debt", "Long Term Debt"]:
            if label in balance.index:
                total_debt = float(balance.loc[label].iloc[0])
                break

        equity = None
        for label in ["Stockholders Equity", "Common Stock Equity",
                      "Total Equity Gross Minority Interest"]:
            if label in balance.index:
                equity = float(balance.loc[label].iloc[0])
                break

        if equity is None or equity <= 0:
            return None
        return total_debt / equity

    except (KeyError, IndexError, ZeroDivisionError, ValueError) as exc:
        logger.debug("Debt-to-equity failed: %s", exc)
        return None


def calculate_roce(stock: yf.Ticker) -> float | None:
    """
    Return on Capital Employed = EBIT / Capital Employed.
    Capital Employed = Total Assets - Current Liabilities.
    Returns decimal.
    """
    income = stock.income_stmt
    balance = stock.balance_sheet
    try:
        ebit = float(income.loc["Operating Income"].iloc[0])
        total_assets = float(balance.loc["Total Assets"].iloc[0])
        current_liabilities = float(balance.loc["Current Liabilities"].iloc[0])
        capital_employed = total_assets - current_liabilities
        if capital_employed <= 0:
            return None
        return ebit / capital_employed
    except (KeyError, IndexError, ZeroDivisionError, ValueError) as exc:
        logger.debug("ROCE failed: %s", exc)
        return None


def calculate_roic_v2(stock: yf.Ticker) -> float | None:
    """
    ROIC using a debt+equity definition of invested capital.

    NOPAT = Operating Income × (1 - 0.25)
    Invested Capital = Total Debt + Total Equity - Cash

    The existing calculate_roic() uses Total Assets - CL - Cash.
    This version aligns with the debt+equity convention used by most analysts.
    Returns decimal.
    """
    income = stock.income_stmt
    balance = stock.balance_sheet
    try:
        operating_income = float(income.loc["Operating Income"].iloc[0])
        nopat = operating_income * 0.75  # assumes 25% tax rate

        total_debt = 0.0
        for label in ["Total Debt", "Long Term Debt"]:
            if label in balance.index:
                total_debt = float(balance.loc[label].iloc[0])
                break

        equity = None
        for label in ["Stockholders Equity", "Common Stock Equity",
                      "Total Equity Gross Minority Interest"]:
            if label in balance.index:
                equity = float(balance.loc[label].iloc[0])
                break

        cash = float(balance.loc["Cash And Cash Equivalents"].iloc[0])

        if equity is None:
            return None
        invested_capital = total_debt + equity - cash
        if invested_capital <= 0:
            return None
        return nopat / invested_capital

    except (KeyError, IndexError, ZeroDivisionError, ValueError) as exc:
        logger.debug("ROIC v2 failed: %s", exc)
        return None


def calculate_owner_earnings(stock: yf.Ticker) -> float | None:
    """
    Owner Earnings (Buffett) = Net Income + D&A - Capex.
    Returns absolute value in reporting currency units.
    """
    income = stock.income_stmt
    cashflow = stock.cashflow
    try:
        net_income = float(income.loc["Net Income"].iloc[0])

        da = 0.0
        for label in ["Depreciation And Amortization", "Reconciled Depreciation"]:
            if label in income.index:
                da = float(income.loc[label].iloc[0])
                break
        if da == 0.0 and "Depreciation And Amortization" in cashflow.index:
            da = float(cashflow.loc["Depreciation And Amortization"].iloc[0])

        capex = 0.0
        for label in ["Capital Expenditure", "Capital Expenditures"]:
            if label in cashflow.index:
                capex = abs(float(cashflow.loc[label].iloc[0]))
                break

        return net_income + da - capex

    except (KeyError, IndexError, ValueError) as exc:
        logger.debug("Owner earnings failed: %s", exc)
        return None


def calculate_owner_earnings_yield(stock: yf.Ticker) -> float | None:
    """Owner Earnings / Market Cap. Returns decimal."""
    try:
        oe = calculate_owner_earnings(stock)
        market_cap = stock.info.get("marketCap")
        if oe is not None and market_cap and float(market_cap) > 0:
            return oe / float(market_cap)
        return None
    except Exception as exc:
        logger.debug("Owner earnings yield failed: %s", exc)
        return None


def calculate_graham_number(stock: yf.Ticker) -> float | None:
    """Graham Number = sqrt(22.5 × EPS × Book Value Per Share)."""
    import math
    try:
        info = stock.info
        eps = info.get("trailingEps")
        bvps = info.get("bookValue")
        if eps is not None and bvps is not None:
            eps_val = float(eps)
            bvps_val = float(bvps)
            product = 22.5 * eps_val * bvps_val
            if product > 0:
                return math.sqrt(product)
        return None
    except Exception as exc:
        logger.debug("Graham Number failed: %s", exc)
        return None


def _growth_from_history(series_current: float, series_prior: float) -> float | None:
    """YoY growth rate. Returns None if prior is zero or negative."""
    if series_prior is None or series_prior == 0:
        return None
    return (series_current - series_prior) / abs(series_prior)


def calculate_revenue_growth(stock: yf.Ticker) -> float | None:
    """YoY revenue growth from two most recent annual income statements."""
    try:
        income = stock.income_stmt
        if income is None or income.shape[1] < 2:
            return None
        for label in ["Total Revenue", "Operating Revenue"]:
            if label in income.index:
                current = float(income.loc[label].iloc[0])
                prior = float(income.loc[label].iloc[1])
                return _growth_from_history(current, prior)
        return None
    except (KeyError, IndexError, ValueError) as exc:
        logger.debug("Revenue growth failed: %s", exc)
        return None


def calculate_eps_growth(stock: yf.Ticker) -> float | None:
    """YoY EPS (basic) growth from two most recent annual income statements."""
    try:
        income = stock.income_stmt
        if income is None or income.shape[1] < 2:
            return None
        for label in ["Basic EPS", "Diluted EPS"]:
            if label in income.index:
                current = float(income.loc[label].iloc[0])
                prior = float(income.loc[label].iloc[1])
                return _growth_from_history(current, prior)
        return None
    except (KeyError, IndexError, ValueError) as exc:
        logger.debug("EPS growth failed: %s", exc)
        return None


def calculate_fcf_growth(stock: yf.Ticker) -> float | None:
    """YoY Free Cash Flow growth from two most recent annual cashflow statements."""
    try:
        cashflow = stock.cashflow
        if cashflow is None or cashflow.shape[1] < 2:
            return None
        if "Free Cash Flow" in cashflow.index:
            current = float(cashflow.loc["Free Cash Flow"].iloc[0])
            prior = float(cashflow.loc["Free Cash Flow"].iloc[1])
            return _growth_from_history(current, prior)
        return None
    except (KeyError, IndexError, ValueError) as exc:
        logger.debug("FCF growth failed: %s", exc)
        return None


# ── Compute-once helper ───────────────────────────────────────────────────────

def compute_all_metrics(stock: yf.Ticker) -> dict[str, float | None]:
    """
    Compute all raw metrics once from a single yf.Ticker object.

    Pass the returned dict to build_*_metrics() and framework analyze functions
    to avoid redundant API calls. All 7 original keys are preserved unchanged.
    New keys are appended; existing callers that rely on specific keys are unaffected.
    """
    import math

    raw = {
        # ── Original 7 keys (backward-compatible) ───────────────────────────
        "roic": calculate_roic(stock),
        "fcf_conversion": calculate_fcf_conversion(stock),
        "net_debt_ebitda": calculate_net_debt_ebitda(stock),
        "peg_ratio": calculate_peg_ratio(stock),
        "price_to_book": calculate_price_to_book(stock),
        "current_ratio": calculate_current_ratio(stock),
        "earnings_growth": calculate_trailing_earnings_growth(stock),
        # ── New profitability keys ───────────────────────────────────────────
        "roe": calculate_roe(stock),
        "roa": calculate_roa(stock),
        "roce": calculate_roce(stock),
        "operating_margin": calculate_operating_margin(stock),
        "net_margin": calculate_net_margin(stock),
        "gross_margin": calculate_gross_margin(stock),
        "roic_v2": calculate_roic_v2(stock),
        # ── New valuation keys ───────────────────────────────────────────────
        "pe_ratio": calculate_pe_ratio(stock),
        "earnings_yield": calculate_earnings_yield(stock),
        "fcf_yield": calculate_fcf_yield(stock),
        "ev_fcf": calculate_ev_fcf(stock),
        # ── New balance sheet keys ───────────────────────────────────────────
        "debt_to_equity": calculate_debt_to_equity(stock),
        # ── New cash flow keys ───────────────────────────────────────────────
        "owner_earnings_yield": calculate_owner_earnings_yield(stock),
        # ── New growth keys ──────────────────────────────────────────────────
        "revenue_growth": calculate_revenue_growth(stock),
        "eps_growth": calculate_eps_growth(stock),
        "fcf_growth": calculate_fcf_growth(stock),
    }
    return {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in raw.items()}


# ── Pillar metric builders ─────────────────────────────────────────────────────

def build_fortress_metrics(
    stock: yf.Ticker,
    precomputed: dict[str, float | None] | None = None,
) -> list[MetricDrillDown]:
    """Build The Fortress pillar (financial health) metrics."""
    metrics = []
    pc = precomputed or {}

    roic = pc.get("roic") if precomputed is not None else calculate_roic(stock)
    if roic is not None:
        metrics.append(MetricDrillDown(
            metric_name="ROIC",
            raw_value=round(roic * 100, 2),
            normalized_score=normalize_roic(roic),
            source="calculated",
            evidence=f"ROIC = {roic * 100:.1f}% (yfinance income_stmt + balance_sheet)",
            confidence="high",
        ))

    fcf = pc.get("fcf_conversion") if precomputed is not None else calculate_fcf_conversion(stock)
    if fcf is not None:
        metrics.append(MetricDrillDown(
            metric_name="FCF Conversion",
            raw_value=round(fcf, 3),
            normalized_score=normalize_fcf_conversion(fcf),
            source="calculated",
            evidence=f"FCF / Net Income = {fcf:.2f}x (from yfinance cashflow)",
            confidence="high",
        ))

    nd_ebitda = (
        pc.get("net_debt_ebitda") if precomputed is not None else calculate_net_debt_ebitda(stock)
    )
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


def build_engine_metrics(
    stock: yf.Ticker,
    precomputed: dict[str, float | None] | None = None,
) -> list[MetricDrillDown]:
    """Build The Engine pillar (business quality) metrics."""
    metrics = []
    pc = precomputed or {}

    roic = pc.get("roic") if precomputed is not None else calculate_roic(stock)
    if roic is not None:
        metrics.append(MetricDrillDown(
            metric_name="ROIC",
            raw_value=round(roic * 100, 2),
            normalized_score=normalize_roic(roic),
            source="calculated",
            evidence=f"ROIC = {roic * 100:.1f}% — core quality signal",
            confidence="high",
        ))

    gross_margin = (
        pc.get("gross_margin") if precomputed is not None else calculate_gross_margin(stock)
    )
    if gross_margin is not None:
        try:
            score = normalize_gross_margin(gross_margin)
            metrics.append(MetricDrillDown(
                metric_name="Gross Margin",
                raw_value=round(gross_margin * 100, 2),
                normalized_score=score,
                source="yfinance",
                evidence=f"Gross margin = {gross_margin * 100:.1f}%",
                confidence="high",
            ))
        except Exception as exc:
            logger.debug("Gross margin metric build failed: %s", exc)

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
        # Buyback yield would require summing repurchaseOfStock from the cashflow statement,
        # which yfinance exposes inconsistently across tickers.
        shareholder_yield = dividend_yield
        if shareholder_yield > 0:
            score = max(0, min(100, int(shareholder_yield * 1000)))
            metrics.append(MetricDrillDown(
                metric_name="Shareholder Yield",
                raw_value=round(shareholder_yield * 100, 2),
                normalized_score=score,
                source="yfinance",
                evidence=(
                    f"Dividend yield = {shareholder_yield * 100:.2f}%"
                    " (buyback yield unavailable from yfinance)"
                ),
                confidence="medium",
            ))

    except Exception as exc:
        logger.debug("Alignment metrics failed: %s", exc)

    return metrics
