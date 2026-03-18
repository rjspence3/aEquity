"""Letter-grade assignment for individual metrics and aggregated scores.

Grades use the standard US academic scale (A+ → F) with a numeric equivalent
for weighted averaging. INCOMPLETE is returned when too many inputs are missing.
"""

from __future__ import annotations

from enum import Enum

from tools.metric_thresholds import _GRADE_LEVELS, THRESHOLDS


class Grade(Enum):
    A_PLUS = "A+"
    A = "A"
    A_MINUS = "A-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"
    C_PLUS = "C+"
    C = "C"
    C_MINUS = "C-"
    D = "D"
    F = "F"
    INCOMPLETE = "INC"


# GPA-style numeric value for each grade, used for weighted averaging.
GRADE_NUMERIC: dict[Grade, float] = {
    Grade.A_PLUS:   4.3,
    Grade.A:        4.0,
    Grade.A_MINUS:  3.7,
    Grade.B_PLUS:   3.3,
    Grade.B:        3.0,
    Grade.B_MINUS:  2.7,
    Grade.C_PLUS:   2.3,
    Grade.C:        2.0,
    Grade.C_MINUS:  1.7,
    Grade.D:        1.0,
    Grade.F:        0.0,
    Grade.INCOMPLETE: float("nan"),
}

# Midpoint 0-100 score for each grade — used to convert grades back to
# the existing pipeline's numeric score format.
GRADE_TO_SCORE: dict[Grade, int] = {
    Grade.A_PLUS:   97,
    Grade.A:        93,
    Grade.A_MINUS:  90,
    Grade.B_PLUS:   87,
    Grade.B:        83,
    Grade.B_MINUS:  80,
    Grade.C_PLUS:   77,
    Grade.C:        73,
    Grade.C_MINUS:  69,
    Grade.D:        55,
    Grade.F:        30,
    Grade.INCOMPLETE: 50,
}

# Enum member lookup by threshold level name (matches _GRADE_LEVELS keys)
_LEVEL_TO_GRADE: dict[str, Grade] = {
    "A_plus":  Grade.A_PLUS,
    "A":       Grade.A,
    "A_minus": Grade.A_MINUS,
    "B_plus":  Grade.B_PLUS,
    "B":       Grade.B,
    "B_minus": Grade.B_MINUS,
    "C_plus":  Grade.C_PLUS,
    "C":       Grade.C,
    "C_minus": Grade.C_MINUS,
    "D":       Grade.D,
}


def grade_metric(metric_name: str, value: float | None) -> Grade:
    """Return the letter grade for a single metric value.

    Returns Grade.INCOMPLETE if value is None.
    Returns Grade.F if metric_name is unknown or value falls below D threshold.
    """
    if value is None:
        return Grade.INCOMPLETE

    thresholds = THRESHOLDS.get(metric_name)
    if thresholds is None:
        return Grade.F

    higher_is_better: bool = thresholds["higher_is_better"]  # type: ignore[assignment]

    for level in _GRADE_LEVELS:
        cutoff: float = thresholds[level]  # type: ignore[literal-required]
        if higher_is_better:
            if value >= cutoff:
                return _LEVEL_TO_GRADE[level]
        else:
            if value <= cutoff:
                return _LEVEL_TO_GRADE[level]

    return Grade.F


def grade_to_numeric(grade: Grade) -> float:
    """Convert a Grade to its GPA-scale numeric equivalent."""
    return GRADE_NUMERIC[grade]


def grade_to_score(grade: Grade) -> int:
    """Convert a Grade to a 0-100 integer score."""
    return GRADE_TO_SCORE[grade]


def numeric_to_grade(value: float) -> Grade:
    """Convert a GPA-scale average back to the nearest letter grade.

    Useful when aggregating grades as floats, then converting back.
    """
    if value >= 4.15:
        return Grade.A_PLUS
    if value >= 3.85:
        return Grade.A
    if value >= 3.5:
        return Grade.A_MINUS
    if value >= 3.15:
        return Grade.B_PLUS
    if value >= 2.85:
        return Grade.B
    if value >= 2.5:
        return Grade.B_MINUS
    if value >= 2.15:
        return Grade.C_PLUS
    if value >= 1.85:
        return Grade.C
    if value >= 1.35:
        return Grade.C_MINUS
    if value >= 0.5:
        return Grade.D
    return Grade.F


def aggregate_grades(
    grades: list[Grade],
    weights: list[float] | None = None,
    min_coverage: float = 0.60,
) -> Grade:
    """Compute weighted average of grades.

    Returns Grade.INCOMPLETE if available (non-INCOMPLETE) grades represent
    less than min_coverage of the total weight.

    Args:
        grades: List of Grade values.
        weights: Optional weights matching grades length. Defaults to equal weight.
        min_coverage: Minimum fraction of weight that must be non-INCOMPLETE.
    """
    if not grades:
        return Grade.INCOMPLETE

    if weights is None:
        weights = [1.0] * len(grades)

    if len(weights) != len(grades):
        raise ValueError("grades and weights must have equal length")

    total_weight = sum(weights)
    available_weight = 0.0
    weighted_sum = 0.0

    for grade, weight in zip(grades, weights, strict=False):
        if grade is Grade.INCOMPLETE:
            continue
        available_weight += weight
        weighted_sum += GRADE_NUMERIC[grade] * weight

    if total_weight == 0 or (available_weight / total_weight) < min_coverage:
        return Grade.INCOMPLETE

    return numeric_to_grade(weighted_sum / available_weight)
