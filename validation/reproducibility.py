"""Script 1: Verify LLM-dependent scores (moat, understandability) are stable across N runs."""

import csv
import logging
import math
from pathlib import Path

from models import CompanyAnalysis

from validation._helpers import ensure_output_dir, run_analysis_safe

logger = logging.getLogger(__name__)

TICKERS = ["AAPL", "MSFT", "XOM", "WMT", "TSLA"]
N_RUNS = 3
VARIANCE_THRESHOLD = 10  # flag if stddev > 10 points across runs


def extract_llm_scores(analysis: CompanyAnalysis) -> dict[str, int]:
    """
    Extract moat_score and understandability_score from analysis.

    Finds "The Moat" pillar, then finds MetricDrillDown by metric_name.
    Returns {"moat": int, "understandability": int}.
    Matching order: exact name first, then case-insensitive partial match
    ("moat" / "understand"), then falls back to pillar score if neither found.
    """
    moat_pillar = next(
        (p for p in analysis.pillars if p.pillar_name == "The Moat"), None
    )

    if moat_pillar is None:
        return {"moat": 50, "understandability": 50}

    moat_score: int | None = None
    understandability_score: int | None = None

    # Pass 1: exact match on the names the current pipeline emits.
    for metric in moat_pillar.metrics:
        if metric.metric_name == "Moat Score":
            moat_score = metric.normalized_score
        elif metric.metric_name == "Understandability":
            understandability_score = metric.normalized_score

    # Pass 2: case-insensitive partial match for any future name variations.
    if moat_score is None or understandability_score is None:
        for metric in moat_pillar.metrics:
            name_lower = metric.metric_name.lower()
            if moat_score is None and "moat" in name_lower and "understand" not in name_lower:
                moat_score = metric.normalized_score
            elif understandability_score is None and "understand" in name_lower:
                understandability_score = metric.normalized_score

    return {
        "moat": moat_score if moat_score is not None else moat_pillar.score,
        "understandability": understandability_score if understandability_score is not None else moat_pillar.score,
    }


def run_ticker_n_times(ticker: str, n: int) -> list[dict[str, int | None]]:
    """
    Run analyze_ticker n times for ticker, forcing fresh LLM calls each time.

    Returns list of dicts: [{"moat": int, "understandability": int, "composite": int}, ...]
    On failure for a run, records None values for that run.
    """
    results = []
    for run_num in range(1, n + 1):
        logger.info("Run %d/%d for %s", run_num, n, ticker)
        analysis = run_analysis_safe(ticker)
        if analysis is None:
            results.append({"moat": None, "understandability": None, "composite": None})
        else:
            scores = extract_llm_scores(analysis)
            results.append({
                "moat": scores["moat"],
                "understandability": scores["understandability"],
                "composite": analysis.overall_score,
            })
    return results


def _stddev(values: list[int | None]) -> float:
    """Compute population standard deviation, skipping None values."""
    valid = [v for v in values if v is not None]
    if len(valid) < 2:
        return 0.0
    mean = sum(valid) / len(valid)
    variance = sum((v - mean) ** 2 for v in valid) / len(valid)
    return math.sqrt(variance)


def _mean(values: list[int | None]) -> float | None:
    """Compute mean, skipping None values."""
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(valid) / len(valid)


def compute_variance_report(ticker: str, runs: list[dict]) -> dict:
    """
    Given N run results, compute mean and stddev for moat, understandability, composite.

    Returns structured dict including:
    - mean and stddev for moat, understandability, composite
    - flagged: True if stddev > VARIANCE_THRESHOLD for moat or understandability
    """
    moat_values = [r.get("moat") for r in runs]
    understand_values = [r.get("understandability") for r in runs]
    composite_values = [r.get("composite") for r in runs]

    moat_stddev = _stddev(moat_values)
    understand_stddev = _stddev(understand_values)
    composite_stddev = _stddev(composite_values)

    flagged = moat_stddev > VARIANCE_THRESHOLD or understand_stddev > VARIANCE_THRESHOLD

    row: dict = {"ticker": ticker, "flagged": flagged}
    for i, run in enumerate(runs, start=1):
        row[f"run{i}_moat"] = run.get("moat")
        row[f"run{i}_understand"] = run.get("understandability")
        row[f"run{i}_composite"] = run.get("composite")

    row["moat_stddev"] = round(moat_stddev, 1)
    row["understand_stddev"] = round(understand_stddev, 1)
    row["composite_stddev"] = round(composite_stddev, 1)
    row["moat_mean"] = round(_mean(moat_values) or 0.0, 1)
    row["understand_mean"] = round(_mean(understand_values) or 0.0, 1)
    row["composite_mean"] = round(_mean(composite_values) or 0.0, 1)

    return row


def main(tickers: list[str] = TICKERS) -> int:
    """
    Run reproducibility check. Print results. Save CSV.

    Returns exit code: 1 if any ticker flagged, 0 otherwise.
    """
    output_dir = ensure_output_dir()
    output_path = output_dir / "reproducibility.csv"

    all_reports = []
    flagged_count = 0

    for ticker in tickers:
        logger.info("Checking reproducibility for %s (%d runs)", ticker, N_RUNS)
        runs = run_ticker_n_times(ticker, N_RUNS)
        report = compute_variance_report(ticker, runs)
        all_reports.append(report)
        if report["flagged"]:
            flagged_count += 1

        status = "[FLAGGED]" if report["flagged"] else "[OK]"
        print(
            f"{ticker}: "
            f"moat={report['moat_mean']:.0f}±{report['moat_stddev']}  "
            f"understand={report['understand_mean']:.0f}±{report['understand_stddev']}  "
            f"composite={report['composite_mean']:.0f}±{report['composite_stddev']}  "
            f"{status}"
        )

    avg_moat_stddev = sum(r["moat_stddev"] for r in all_reports) / len(all_reports) if all_reports else 0.0
    avg_understand_stddev = sum(r["understand_stddev"] for r in all_reports) / len(all_reports) if all_reports else 0.0
    print("---")
    print(f"Average moat stddev: {avg_moat_stddev:.1f} | Average understand stddev: {avg_understand_stddev:.1f}")
    print(f"Flagged: {flagged_count}/{len(tickers)} tickers")

    if all_reports:
        run_cols = []
        for metric in ("moat", "understand", "composite"):
            for i in range(1, N_RUNS + 1):
                run_cols.append(f"run{i}_{metric}")
            run_cols.append(f"{metric}_stddev")
            run_cols.append(f"{metric}_mean")
        fieldnames = ["ticker"] + run_cols + ["flagged"]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_reports)
        logger.info("Saved reproducibility report to %s", output_path)

    return 1 if flagged_count > 0 else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
