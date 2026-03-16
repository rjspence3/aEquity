"""CLI entry point for validation scripts.

Usage:
    python -m validation.run --all
    python -m validation.run --reproducibility
    python -m validation.run --metrics
    python -m validation.run --consensus [--skip-new]
"""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="validation",
        description="aEquity validation suite — spot-check pipeline outputs",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Run all three validation scripts in order",
    )
    group.add_argument(
        "--reproducibility",
        action="store_true",
        help="Script 1: LLM score stability check",
    )
    group.add_argument(
        "--metrics",
        action="store_true",
        help="Script 2: Metric accuracy spot-check",
    )
    group.add_argument(
        "--consensus",
        action="store_true",
        help="Script 3: Analyst consensus correlation",
    )
    parser.add_argument(
        "--skip-new",
        action="store_true",
        default=False,
        help="Skip tickers that require a fresh analysis (consensus script only)",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLite database URL (default: settings.database_url)",
    )
    return parser


def main() -> None:
    """Parse args and run the requested validation script(s)."""
    parser = build_parser()
    args = parser.parse_args()

    exit_codes: list[int] = []

    if args.all or args.reproducibility:
        from validation.reproducibility import main as run_reproducibility
        code = run_reproducibility()
        exit_codes.append(code)

    if args.all or args.metrics:
        from validation.metric_accuracy import main as run_metrics
        code = run_metrics(db_url=args.db_url)
        exit_codes.append(code)

    if args.all or args.consensus:
        from validation.analyst_consensus import main as run_consensus
        code = run_consensus(skip_new=args.skip_new, db_url=args.db_url)
        exit_codes.append(code)

    sys.exit(1 if any(c != 0 for c in exit_codes) else 0)


if __name__ == "__main__":
    main()
