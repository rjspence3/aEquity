"""Script 2: Spot-check calculated metrics against reference values."""

import csv
import json
import logging
from pathlib import Path

from config import settings

from validation._helpers import ensure_output_dir, get_cached_analysis, run_analysis_safe

logger = logging.getLogger(__name__)

CLEAN_TICKERS = ["AAPL", "MSFT", "JNJ", "COST", "PG"]
MESSY_TICKERS = ["SPG", "JPM", "UBER", "T", "PLTR"]

# Threshold for pass/fail: 10% relative difference (or absolute threshold for near-zero values)
PCT_DIFF_THRESHOLD = 10.0
ABS_DIFF_THRESHOLD_NEAR_ZERO = 0.5  # used when reference value is near zero

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "reference_metrics.json"


def load_reference_metrics() -> dict[str, dict]:
    """Load validation/fixtures/reference_metrics.json."""
    with open(FIXTURES_PATH) as f:
        return json.load(f)


def get_our_metrics(ticker: str, db_url: str) -> dict[str, float | None]:
    """
    Pull our calculated metrics for ticker from SQLite or run analysis.

    Returns dict with keys matching reference_metrics.json.
    Converts from pipeline units: roic decimal→pct, gross_margin decimal→pct.
    """
    analysis = get_cached_analysis(ticker, db_url)
    if analysis is None:
        logger.info("No cached analysis for %s, running fresh analysis", ticker)
        analysis = run_analysis_safe(ticker)

    if analysis is None:
        logger.warning("Could not obtain analysis for %s", ticker)
        return {}

    metrics: dict[str, float | None] = {
        "roic_pct": None,
        "fcf_conversion": None,
        "net_debt_ebitda": None,
        "peg_ratio": None,
        "price_to_book": None,
        "current_ratio": None,
        "gross_margin_pct": None,
    }

    # Extract from pillar metrics
    for pillar in analysis.pillars:
        for metric in pillar.metrics:
            name = metric.metric_name
            raw = metric.raw_value

            if name == "ROIC":
                # Pipeline stores as pct already in MetricDrillDown (raw_value = roic * 100)
                metrics["roic_pct"] = raw
            elif name == "FCF Conversion":
                metrics["fcf_conversion"] = raw
            elif name == "Net Debt / EBITDA":
                metrics["net_debt_ebitda"] = raw
            elif name == "Gross Margin":
                # Pipeline stores as pct already in MetricDrillDown (raw_value = grossMargins * 100)
                metrics["gross_margin_pct"] = raw

    # Extract from guru key metrics (price_to_book, peg_ratio, current_ratio)
    for guru in analysis.gurus:
        for metric in guru.key_metrics:
            name = metric.metric_name
            raw = metric.raw_value

            if name == "PEG Ratio" and metrics["peg_ratio"] is None:
                metrics["peg_ratio"] = raw
            elif name == "Price/Book" and metrics["price_to_book"] is None:
                metrics["price_to_book"] = raw
            elif name == "Current Ratio" and metrics["current_ratio"] is None:
                metrics["current_ratio"] = raw

    return metrics


def compare_metrics(ours: dict, reference: dict) -> list[dict]:
    """
    For each metric present in both dicts, compute absolute and percentage diff.

    Flags if pct diff > 10% (or abs diff > threshold for near-zero values).
    Skips metrics where reference value is None (not applicable for this ticker type).
    Returns list of comparison rows.
    """
    results = []
    metric_keys = [
        "roic_pct", "fcf_conversion", "net_debt_ebitda",
        "peg_ratio", "price_to_book", "current_ratio", "gross_margin_pct",
    ]

    for key in metric_keys:
        ref_value = reference.get(key)
        if ref_value is None:
            continue  # Not applicable for this ticker type

        our_value = ours.get(key)
        if our_value is None:
            results.append({
                "metric": key,
                "our_value": None,
                "reference_value": ref_value,
                "abs_diff": None,
                "pct_diff": None,
                "pass_fail": "MISSING",
                "notes": "Our pipeline returned None for this metric",
            })
            continue

        abs_diff = abs(our_value - ref_value)

        # For near-zero reference values, use absolute threshold instead of percentage
        if abs(ref_value) < 1.0:
            pct_diff = abs_diff / max(abs(ref_value), 0.01) * 100
            passed = abs_diff <= ABS_DIFF_THRESHOLD_NEAR_ZERO
        else:
            pct_diff = abs_diff / abs(ref_value) * 100
            passed = pct_diff <= PCT_DIFF_THRESHOLD

        verified = reference.get("verified", True)
        notes = ""
        if not verified:
            notes = "WARNING: reference value unverified"

        results.append({
            "metric": key,
            "our_value": round(our_value, 4),
            "reference_value": ref_value,
            "abs_diff": round(abs_diff, 4),
            "pct_diff": round(pct_diff, 1),
            "pass_fail": "PASS" if passed else "FAIL",
            "notes": notes,
        })

    return results


def print_summary(
    results: dict[str, list[dict]],
    clean_tickers: list[str],
    messy_tickers: list[str],
) -> None:
    """Print pass/fail counts for clean-5 vs messy-5."""

    def _group_stats(tickers: list[str]) -> tuple[int, int]:
        total = 0
        passed = 0
        for ticker in tickers:
            for row in results.get(ticker, []):
                if row["pass_fail"] in ("PASS", "FAIL"):
                    total += 1
                    if row["pass_fail"] == "PASS":
                        passed += 1
        return passed, total

    print(f"\nClean financials ({', '.join(clean_tickers)}):")
    for ticker in clean_tickers:
        ticker_results = results.get(ticker, [])
        if not ticker_results:
            print(f"  {ticker}: no data")
            continue
        t_pass = sum(1 for r in ticker_results if r["pass_fail"] == "PASS")
        t_total = sum(1 for r in ticker_results if r["pass_fail"] in ("PASS", "FAIL"))
        details = []
        for r in ticker_results:
            if r["pass_fail"] == "FAIL":
                details.append(
                    f"{r['metric']}: {r['our_value']} vs {r['reference_value']} "
                    f"[FAIL {r['pct_diff']}%]"
                )
            elif r["pass_fail"] == "PASS":
                details.append(
                    f"{r['metric']}: {r['our_value']} vs {r['reference_value']} [OK]"
                )
        detail_str = ", ".join(details[:3])
        if len(details) > 3:
            detail_str += f" ... (+{len(details) - 3} more)"
        print(f"  {ticker}: {t_pass}/{t_total} metrics pass  ({detail_str})")

    clean_pass, clean_total = _group_stats(clean_tickers)
    print(f"  Clean pass rate: {clean_pass}/{clean_total} ({100 * clean_pass // max(clean_total, 1)}%)")

    print(f"\nMessy financials ({', '.join(messy_tickers)}):")
    for ticker in messy_tickers:
        ticker_results = results.get(ticker, [])
        if not ticker_results:
            print(f"  {ticker}: no data")
            continue
        t_pass = sum(1 for r in ticker_results if r["pass_fail"] == "PASS")
        t_total = sum(1 for r in ticker_results if r["pass_fail"] in ("PASS", "FAIL"))
        skipped = sum(1 for r in ticker_results if r["pass_fail"] == "MISSING")
        print(f"  {ticker}: {t_pass}/{t_total} applicable metrics pass  ({skipped} skipped/missing)")

    messy_pass, messy_total = _group_stats(messy_tickers)
    print(f"  Messy pass rate: {messy_pass}/{messy_total} applicable metrics ({100 * messy_pass // max(messy_total, 1)}%)")


def main(db_url: str | None = None) -> int:
    """Run metric accuracy check. Save CSV. Print summary. Returns exit code."""
    if db_url is None:
        db_url = settings.database_url

    output_dir = ensure_output_dir()
    output_path = output_dir / "metric_accuracy.csv"

    reference = load_reference_metrics()
    all_tickers = CLEAN_TICKERS + MESSY_TICKERS
    all_results: dict[str, list[dict]] = {}
    csv_rows = []

    for ticker in all_tickers:
        group = "clean" if ticker in CLEAN_TICKERS else "messy"
        ticker_ref = reference.get(ticker, {})
        if not ticker_ref:
            logger.warning("No reference data for %s", ticker)
            all_results[ticker] = []
            continue

        logger.info("Checking metric accuracy for %s", ticker)
        our_metrics = get_our_metrics(ticker, db_url)
        comparisons = compare_metrics(our_metrics, ticker_ref)
        all_results[ticker] = comparisons

        for row in comparisons:
            csv_rows.append({
                "ticker": ticker,
                "group": group,
                "metric": row["metric"],
                "our_value": row["our_value"],
                "reference_value": row["reference_value"],
                "abs_diff": row["abs_diff"],
                "pct_diff": row["pct_diff"],
                "pass_fail": row["pass_fail"],
                "notes": row["notes"],
            })

    if csv_rows:
        fieldnames = ["ticker", "group", "metric", "our_value", "reference_value",
                      "abs_diff", "pct_diff", "pass_fail", "notes"]
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
        logger.info("Saved metric accuracy report to %s", output_path)

    print_summary(all_results, CLEAN_TICKERS, MESSY_TICKERS)

    clean_pass = sum(
        1 for t in CLEAN_TICKERS for r in all_results.get(t, []) if r["pass_fail"] == "PASS"
    )
    clean_total = sum(
        1 for t in CLEAN_TICKERS for r in all_results.get(t, []) if r["pass_fail"] in ("PASS", "FAIL")
    )
    clean_rate = clean_pass / clean_total if clean_total > 0 else 0.0
    return 1 if clean_rate < 0.80 else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
