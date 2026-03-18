"""Howard Marks framework: risk-adjusted quality.

Marks emphasizes the price paid for quality. A great company at a terrible
price is a bad investment. Combines valuation (P/E), quality (ROIC), and
leverage (D/E) with roughly equal weight.
"""

from services.grader import Grade, aggregate_grades, grade_metric, grade_to_score

_METRICS = ["pe_ratio", "roic_v2", "debt_to_equity"]
_WEIGHTS = [0.35, 0.40, 0.25]


def analyze_marks(metrics: dict[str, float | None]) -> dict:
    """
    Grade a stock through Howard Marks's risk/reward lens.

    Returns standard framework result dict.
    """
    pe_ratio = metrics.get("pe_ratio")
    roic = metrics.get("roic_v2")
    debt_to_equity = metrics.get("debt_to_equity")

    grades = [
        grade_metric("pe_ratio", pe_ratio),
        grade_metric("roic_v2", roic),
        grade_metric("debt_to_equity", debt_to_equity),
    ]

    overall = aggregate_grades(grades, weights=_WEIGHTS)
    available = sum(1 for g in grades if g is not Grade.INCOMPLETE)

    component_grades = {
        "pe_ratio": grades[0].value,
        "roic_v2": grades[1].value,
        "debt_to_equity": grades[2].value,
    }

    parts = []
    if pe_ratio is not None:
        parts.append(f"P/E {pe_ratio:.1f}x ({grades[0].value})")
    if roic is not None:
        parts.append(f"ROIC {roic * 100:.1f}% ({grades[1].value})")
    if debt_to_equity is not None:
        parts.append(f"D/E {debt_to_equity:.2f}x ({grades[2].value})")

    return {
        "grade": overall.value,
        "score": grade_to_score(overall),
        "component_grades": component_grades,
        "notes": "; ".join(parts) if parts else "Insufficient data",
        "metrics_used": available,
        "metrics_required": len(_METRICS),
    }
