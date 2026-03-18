"""Letter-grade thresholds for all financial metrics.

For higher_is_better metrics: a value >= threshold[grade] earns that grade.
For lower_is_better metrics: a value <= threshold[grade] earns that grade.
Thresholds are ordered from best (A+) to worst (F).
"""

from typing import TypedDict


class MetricThreshold(TypedDict):
    A_plus: float
    A: float
    A_minus: float
    B_plus: float
    B: float
    B_minus: float
    C_plus: float
    C: float
    C_minus: float
    D: float
    higher_is_better: bool


# All raw values are in native units:
#   - ratios as decimals (0.20 = 20%, not 20)
#   - multiples as floats (P/E 15 = 15.0)
#   - negative net debt is net cash (better for debt metrics)
THRESHOLDS: dict[str, MetricThreshold] = {
    # ── Profitability ──────────────────────────────────────────────────────────
    "roe": {
        "A_plus": 0.35, "A": 0.25, "A_minus": 0.20,
        "B_plus": 0.17, "B": 0.15, "B_minus": 0.12,
        "C_plus": 0.10, "C": 0.07, "C_minus": 0.05,
        "D": 0.0,
        "higher_is_better": True,
    },
    "roic": {
        "A_plus": 0.30, "A": 0.22, "A_minus": 0.18,
        "B_plus": 0.15, "B": 0.12, "B_minus": 0.10,
        "C_plus": 0.08, "C": 0.06, "C_minus": 0.04,
        "D": 0.0,
        "higher_is_better": True,
    },
    "roic_v2": {
        "A_plus": 0.30, "A": 0.22, "A_minus": 0.18,
        "B_plus": 0.15, "B": 0.12, "B_minus": 0.10,
        "C_plus": 0.08, "C": 0.06, "C_minus": 0.04,
        "D": 0.0,
        "higher_is_better": True,
    },
    "roa": {
        "A_plus": 0.18, "A": 0.12, "A_minus": 0.10,
        "B_plus": 0.08, "B": 0.07, "B_minus": 0.05,
        "C_plus": 0.04, "C": 0.03, "C_minus": 0.02,
        "D": 0.0,
        "higher_is_better": True,
    },
    "roce": {
        "A_plus": 0.30, "A": 0.22, "A_minus": 0.18,
        "B_plus": 0.15, "B": 0.12, "B_minus": 0.10,
        "C_plus": 0.08, "C": 0.06, "C_minus": 0.04,
        "D": 0.0,
        "higher_is_better": True,
    },
    "operating_margin": {
        "A_plus": 0.30, "A": 0.22, "A_minus": 0.18,
        "B_plus": 0.14, "B": 0.10, "B_minus": 0.07,
        "C_plus": 0.05, "C": 0.03, "C_minus": 0.01,
        "D": 0.0,
        "higher_is_better": True,
    },
    "net_margin": {
        "A_plus": 0.25, "A": 0.18, "A_minus": 0.14,
        "B_plus": 0.10, "B": 0.07, "B_minus": 0.05,
        "C_plus": 0.03, "C": 0.02, "C_minus": 0.01,
        "D": 0.0,
        "higher_is_better": True,
    },
    "gross_margin": {
        "A_plus": 0.70, "A": 0.55, "A_minus": 0.45,
        "B_plus": 0.38, "B": 0.30, "B_minus": 0.22,
        "C_plus": 0.16, "C": 0.12, "C_minus": 0.08,
        "D": 0.0,
        "higher_is_better": True,
    },
    # ── Cash flow ──────────────────────────────────────────────────────────────
    "fcf_conversion": {
        "A_plus": 1.30, "A": 1.15, "A_minus": 1.00,
        "B_plus": 0.90, "B": 0.80, "B_minus": 0.70,
        "C_plus": 0.60, "C": 0.50, "C_minus": 0.40,
        "D": 0.0,
        "higher_is_better": True,
    },
    "fcf_yield": {
        "A_plus": 0.10, "A": 0.07, "A_minus": 0.055,
        "B_plus": 0.045, "B": 0.035, "B_minus": 0.025,
        "C_plus": 0.018, "C": 0.012, "C_minus": 0.007,
        "D": 0.0,
        "higher_is_better": True,
    },
    "owner_earnings_yield": {
        "A_plus": 0.10, "A": 0.07, "A_minus": 0.055,
        "B_plus": 0.045, "B": 0.035, "B_minus": 0.025,
        "C_plus": 0.018, "C": 0.012, "C_minus": 0.007,
        "D": 0.0,
        "higher_is_better": True,
    },
    # ── Valuation ──────────────────────────────────────────────────────────────
    "pe_ratio": {
        "A_plus": 8.0, "A": 11.0, "A_minus": 14.0,
        "B_plus": 17.0, "B": 20.0, "B_minus": 23.0,
        "C_plus": 27.0, "C": 32.0, "C_minus": 40.0,
        "D": 60.0,
        "higher_is_better": False,
    },
    "price_to_book": {
        "A_plus": 0.8, "A": 1.2, "A_minus": 1.7,
        "B_plus": 2.2, "B": 2.8, "B_minus": 3.5,
        "C_plus": 4.5, "C": 6.0, "C_minus": 8.0,
        "D": 15.0,
        "higher_is_better": False,
    },
    "peg_ratio": {
        "A_plus": 0.4, "A": 0.65, "A_minus": 0.9,
        "B_plus": 1.1, "B": 1.3, "B_minus": 1.55,
        "C_plus": 1.8, "C": 2.1, "C_minus": 2.5,
        "D": 3.5,
        "higher_is_better": False,
    },
    "earnings_yield": {
        "A_plus": 0.12, "A": 0.09, "A_minus": 0.07,
        "B_plus": 0.058, "B": 0.05, "B_minus": 0.043,
        "C_plus": 0.035, "C": 0.028, "C_minus": 0.02,
        "D": 0.01,
        "higher_is_better": True,
    },
    "ev_fcf": {
        "A_plus": 8.0, "A": 12.0, "A_minus": 15.0,
        "B_plus": 18.0, "B": 22.0, "B_minus": 26.0,
        "C_plus": 32.0, "C": 40.0, "C_minus": 50.0,
        "D": 70.0,
        "higher_is_better": False,
    },
    # ── Balance sheet ──────────────────────────────────────────────────────────
    "net_debt_ebitda": {
        # Net cash (negative) is best, debt-heavy is worst
        "A_plus": -1.5, "A": -0.5, "A_minus": 0.5,
        "B_plus": 1.0, "B": 1.5, "B_minus": 2.2,
        "C_plus": 2.8, "C": 3.5, "C_minus": 4.2,
        "D": 5.0,
        "higher_is_better": False,
    },
    "current_ratio": {
        "A_plus": 3.0, "A": 2.5, "A_minus": 2.0,
        "B_plus": 1.8, "B": 1.6, "B_minus": 1.4,
        "C_plus": 1.2, "C": 1.0, "C_minus": 0.85,
        "D": 0.7,
        "higher_is_better": True,
    },
    "debt_to_equity": {
        "A_plus": 0.05, "A": 0.15, "A_minus": 0.25,
        "B_plus": 0.40, "B": 0.55, "B_minus": 0.75,
        "C_plus": 1.0, "C": 1.4, "C_minus": 2.0,
        "D": 3.0,
        "higher_is_better": False,
    },
    # ── Growth ─────────────────────────────────────────────────────────────────
    "revenue_growth": {
        "A_plus": 0.25, "A": 0.18, "A_minus": 0.13,
        "B_plus": 0.10, "B": 0.08, "B_minus": 0.06,
        "C_plus": 0.04, "C": 0.02, "C_minus": 0.0,
        "D": -0.05,
        "higher_is_better": True,
    },
    "eps_growth": {
        "A_plus": 0.25, "A": 0.18, "A_minus": 0.13,
        "B_plus": 0.10, "B": 0.08, "B_minus": 0.06,
        "C_plus": 0.04, "C": 0.02, "C_minus": 0.0,
        "D": -0.05,
        "higher_is_better": True,
    },
    "fcf_growth": {
        "A_plus": 0.25, "A": 0.18, "A_minus": 0.13,
        "B_plus": 0.10, "B": 0.08, "B_minus": 0.06,
        "C_plus": 0.04, "C": 0.02, "C_minus": 0.0,
        "D": -0.05,
        "higher_is_better": True,
    },
    "earnings_growth": {
        "A_plus": 0.25, "A": 0.18, "A_minus": 0.13,
        "B_plus": 0.10, "B": 0.08, "B_minus": 0.06,
        "C_plus": 0.04, "C": 0.02, "C_minus": 0.0,
        "D": -0.05,
        "higher_is_better": True,
    },
}

# Ordered from best to worst — used by grade_metric() to find the highest
# grade the value qualifies for.
_GRADE_LEVELS = [
    "A_plus", "A", "A_minus",
    "B_plus", "B", "B_minus",
    "C_plus", "C", "C_minus",
    "D",
]
