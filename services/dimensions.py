"""Dimension-based grading: 8 analytical dimensions → weighted overall grade.

Each dimension groups related metrics. Weighted average of available dimension
grades produces the company's overall letter grade.
"""

from __future__ import annotations

from services.grader import Grade, aggregate_grades, grade_metric

# Dimension weights (must sum to 1.0)
DIMENSION_WEIGHTS: dict[str, float] = {
    "profitability":         0.20,   # ROE, ROIC, net margin
    "moat":                  0.15,   # gross margin, operating margin stability
    "balance_sheet":         0.15,   # D/E, current ratio
    "cash_flow":             0.15,   # FCF yield, FCF conversion
    "valuation":             0.15,   # P/E, FCF yield, PEG
    "earnings_consistency":  0.10,   # earnings growth direction
    "growth":                0.05,   # revenue / EPS growth
    "management":            0.05,   # owner earnings yield, insider proxy
}

_MOAT_THRESHOLDS = {
    "wide":    {"gross_margin": 0.50, "operating_margin": 0.20},
    "narrow":  {"gross_margin": 0.35, "operating_margin": 0.12},
    "uncertain": {"gross_margin": 0.20, "operating_margin": 0.05},
}


def _grade_dimension(
    metric_names: list[str],
    metrics: dict[str, float | None],
    weights: list[float] | None = None,
) -> Grade:
    """Grade a list of metrics and aggregate into a single dimension grade."""
    grades = [grade_metric(name, metrics.get(name)) for name in metric_names]
    return aggregate_grades(grades, weights=weights)


def calculate_dimension_grades(metrics: dict[str, float | None]) -> dict[str, str]:
    """
    Calculate all 8 dimension grades from the precomputed metrics dict.

    Returns a dict mapping dimension name → letter grade string.
    """
    profitability_grade = _grade_dimension(
        ["roe", "roic", "net_margin"],
        metrics,
        weights=[0.40, 0.40, 0.20],
    )

    moat_grade = _grade_dimension(
        ["gross_margin", "operating_margin"],
        metrics,
        weights=[0.55, 0.45],
    )

    balance_sheet_grade = _grade_dimension(
        ["debt_to_equity", "current_ratio"],
        metrics,
        weights=[0.55, 0.45],
    )

    cash_flow_grade = _grade_dimension(
        ["fcf_yield", "fcf_conversion"],
        metrics,
        weights=[0.55, 0.45],
    )

    valuation_grade = _grade_dimension(
        ["pe_ratio", "peg_ratio", "earnings_yield"],
        metrics,
        weights=[0.35, 0.35, 0.30],
    )

    # Earnings consistency: positive earnings_growth is the primary signal
    # We use a simple binary: positive growth = B, negative = D, None = INC
    eg = metrics.get("earnings_growth")
    if eg is None:
        consistency_grade = Grade.INCOMPLETE
    elif eg >= 0.08:
        consistency_grade = grade_metric("earnings_growth", eg)
    elif eg >= 0:
        consistency_grade = Grade.C
    else:
        consistency_grade = Grade.D

    growth_grade = _grade_dimension(
        ["revenue_growth", "eps_growth"],
        metrics,
        weights=[0.50, 0.50],
    )

    management_grade = _grade_dimension(
        ["owner_earnings_yield"],
        metrics,
    )

    return {
        "profitability":        profitability_grade.value,
        "moat":                 moat_grade.value,
        "balance_sheet":        balance_sheet_grade.value,
        "cash_flow":            cash_flow_grade.value,
        "valuation":            valuation_grade.value,
        "earnings_consistency": consistency_grade.value,
        "growth":               growth_grade.value,
        "management":           management_grade.value,
    }


def calculate_overall_grade(dimension_grades: dict[str, str]) -> Grade:
    """
    Weighted average of dimension grades → overall company grade.

    Requires at least 60% coverage (non-INC dimensions) by weight.
    """
    grades = []
    weights = []
    for dim, weight in DIMENSION_WEIGHTS.items():
        grade_str = dimension_grades.get(dim, "INC")
        # Find the Grade enum member matching this string
        matched = next(
            (g for g in Grade if g.value == grade_str),
            Grade.INCOMPLETE,
        )
        grades.append(matched)
        weights.append(weight)

    return aggregate_grades(grades, weights=weights, min_coverage=0.60)


def classify_moat_type(metrics: dict[str, float | None]) -> str:
    """Classify moat width based on gross and operating margin thresholds.

    Returns one of: 'wide', 'narrow', 'uncertain', 'none'.
    """
    gross_margin = metrics.get("gross_margin")
    operating_margin = metrics.get("operating_margin")

    if gross_margin is None and operating_margin is None:
        return "uncertain"

    for moat_type in ("wide", "narrow", "uncertain"):
        thresholds = _MOAT_THRESHOLDS[moat_type]
        gm_ok = gross_margin is None or gross_margin >= thresholds["gross_margin"]
        om_ok = operating_margin is None or operating_margin >= thresholds["operating_margin"]
        if gm_ok and om_ok:
            return moat_type

    return "none"
