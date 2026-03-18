"""Framework registry for the 4 new guru frameworks.

The existing 4 guru scoring functions (_score_buffett, _score_lynch,
_score_graham, _score_damodaran) remain in pipeline.py for backward
compatibility with existing tests. This registry covers the 4 additions.
"""

from frameworks.greenblatt import analyze_greenblatt
from frameworks.marks import analyze_marks
from frameworks.munger import analyze_munger
from frameworks.smith import analyze_smith

NEW_GURU_FRAMEWORKS: dict[str, callable] = {
    "Charlie Munger": analyze_munger,
    "Joel Greenblatt": analyze_greenblatt,
    "Howard Marks": analyze_marks,
    "Terry Smith": analyze_smith,
}


def run_new_frameworks(metrics: dict[str, float | None]) -> dict[str, dict]:
    """Run all 4 new guru frameworks. Returns {guru_name: result_dict}."""
    return {name: fn(metrics) for name, fn in NEW_GURU_FRAMEWORKS.items()}
