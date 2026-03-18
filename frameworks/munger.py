"""Charlie Munger framework: quality business at a fair price.

Munger focuses on high returns on invested capital, wide operating margins,
and liquidity. He avoids overpaying and prizes mental-model simplicity.
"""

from services.grader import Grade, aggregate_grades, grade_metric, grade_to_score

_METRICS = ["roic_v2", "operating_margin", "current_ratio"]
_WEIGHTS = [0.40, 0.35, 0.25]


def analyze_munger(metrics: dict[str, float | None]) -> dict:
    """
    Grade a stock through Charlie Munger's lens.

    Returns:
        grade: str            — overall letter grade
        score: int            — 0-100 equivalent
        component_grades: dict — per-metric letter grades
        notes: str            — human-readable summary
        metrics_used: int     — metrics that were available
        metrics_required: int — total metrics in framework
    """
    roic = metrics.get("roic_v2")
    operating_margin = metrics.get("operating_margin")
    current_ratio = metrics.get("current_ratio")

    grades = [
        grade_metric("roic_v2", roic),
        grade_metric("operating_margin", operating_margin),
        grade_metric("current_ratio", current_ratio),
    ]

    overall = aggregate_grades(grades, weights=_WEIGHTS)
    available = sum(1 for g in grades if g is not Grade.INCOMPLETE)

    component_grades = {
        "roic_v2": grades[0].value,
        "operating_margin": grades[1].value,
        "current_ratio": grades[2].value,
    }

    parts = []
    if roic is not None:
        parts.append(f"ROIC {roic * 100:.1f}% ({grades[0].value})")
    if operating_margin is not None:
        parts.append(f"Op Margin {operating_margin * 100:.1f}% ({grades[1].value})")
    if current_ratio is not None:
        parts.append(f"Current Ratio {current_ratio:.2f}x ({grades[2].value})")

    return {
        "grade": overall.value,
        "score": grade_to_score(overall),
        "component_grades": component_grades,
        "notes": "; ".join(parts) if parts else "Insufficient data",
        "metrics_used": available,
        "metrics_required": len(_METRICS),
    }
