"""Terry Smith framework: Fundsmith quality compounders.

Smith's three-part philosophy:
  1. Only invest in good businesses (ROIC > 20%, high gross margin)
  2. Don't overpay (FCF yield, low debt)
  3. Do nothing — just hold quality compounders

Hard cutoffs are enforced: ROIC < 15% or gross margin < 30% earns a floor of C-.
"""

from services.grader import Grade, aggregate_grades, grade_metric, grade_to_score

_METRICS = ["roic_v2", "gross_margin", "fcf_conversion", "debt_to_equity"]
_WEIGHTS = [0.35, 0.30, 0.20, 0.15]

_ROIC_FLOOR = 0.15       # below this, business quality disqualifies
_GROSS_MARGIN_FLOOR = 0.30  # below this, moat is too thin


def analyze_smith(metrics: dict[str, float | None]) -> dict:
    """
    Grade a stock through Terry Smith's (Fundsmith) quality lens.

    Applies hard quality floors: if ROIC < 15% or gross margin < 30%, the
    overall score is capped at C- regardless of other metrics.

    Returns standard framework result dict.
    """
    roic = metrics.get("roic_v2")
    gross_margin = metrics.get("gross_margin")
    fcf_conversion = metrics.get("fcf_conversion")
    debt_to_equity = metrics.get("debt_to_equity")

    grades = [
        grade_metric("roic_v2", roic),
        grade_metric("gross_margin", gross_margin),
        grade_metric("fcf_conversion", fcf_conversion),
        grade_metric("debt_to_equity", debt_to_equity),
    ]

    overall = aggregate_grades(grades, weights=_WEIGHTS)
    available = sum(1 for g in grades if g is not Grade.INCOMPLETE)

    # Hard quality floors — Smith would not buy these businesses at any price
    disqualified = False
    disqualify_reasons = []
    if roic is not None and roic < _ROIC_FLOOR:
        disqualified = True
        disqualify_reasons.append(f"ROIC {roic * 100:.1f}% < {_ROIC_FLOOR * 100:.0f}% floor")
    if gross_margin is not None and gross_margin < _GROSS_MARGIN_FLOOR:
        disqualified = True
        disqualify_reasons.append(
            f"Gross Margin {gross_margin * 100:.1f}% < {_GROSS_MARGIN_FLOOR * 100:.0f}% floor"
        )

    if disqualified and overall not in (Grade.D, Grade.F, Grade.INCOMPLETE):
        # Cap at C- for businesses that fail the quality screen
        overall = Grade.C_MINUS

    component_grades = {
        "roic_v2": grades[0].value,
        "gross_margin": grades[1].value,
        "fcf_conversion": grades[2].value,
        "debt_to_equity": grades[3].value,
    }

    parts = []
    if roic is not None:
        parts.append(f"ROIC {roic * 100:.1f}% ({grades[0].value})")
    if gross_margin is not None:
        parts.append(f"Gross Margin {gross_margin * 100:.1f}% ({grades[1].value})")
    if fcf_conversion is not None:
        parts.append(f"FCF Conv {fcf_conversion:.2f}x ({grades[2].value})")
    if debt_to_equity is not None:
        parts.append(f"D/E {debt_to_equity:.2f}x ({grades[3].value})")
    if disqualify_reasons:
        parts.append(f"[capped: {'; '.join(disqualify_reasons)}]")

    return {
        "grade": overall.value,
        "score": grade_to_score(overall),
        "component_grades": component_grades,
        "notes": "; ".join(parts) if parts else "Insufficient data",
        "metrics_used": available,
        "metrics_required": len(_METRICS),
        "disqualified": disqualified,
    }
