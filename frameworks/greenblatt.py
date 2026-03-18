"""Joel Greenblatt framework: Magic Formula investing.

Magic Formula ranks stocks by Earnings Yield and ROIC simultaneously,
buying the intersection of cheap (high earnings yield) and good (high ROIC).
Equal weight to both pillars.
"""

from services.grader import Grade, aggregate_grades, grade_metric, grade_to_score

_METRICS = ["earnings_yield", "roic_v2"]
_WEIGHTS = [0.50, 0.50]


def analyze_greenblatt(metrics: dict[str, float | None]) -> dict:
    """
    Grade a stock through Joel Greenblatt's Magic Formula lens.

    Returns standard framework result dict.
    """
    earnings_yield = metrics.get("earnings_yield")
    roic = metrics.get("roic_v2")

    grades = [
        grade_metric("earnings_yield", earnings_yield),
        grade_metric("roic_v2", roic),
    ]

    overall = aggregate_grades(grades, weights=_WEIGHTS)
    available = sum(1 for g in grades if g is not Grade.INCOMPLETE)

    component_grades = {
        "earnings_yield": grades[0].value,
        "roic_v2": grades[1].value,
    }

    parts = []
    if earnings_yield is not None:
        parts.append(f"Earnings Yield {earnings_yield * 100:.1f}% ({grades[0].value})")
    if roic is not None:
        parts.append(f"ROIC {roic * 100:.1f}% ({grades[1].value})")

    return {
        "grade": overall.value,
        "score": grade_to_score(overall),
        "component_grades": component_grades,
        "notes": "; ".join(parts) if parts else "Insufficient data",
        "metrics_used": available,
        "metrics_required": len(_METRICS),
    }
