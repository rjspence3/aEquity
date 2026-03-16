"""CLI entry point for single-stock analysis."""

import argparse
import json
import logging
import sys

import anthropic

from pipeline import analyze_ticker

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="aEquity — run guru-style analysis on a single stock ticker."
    )
    parser.add_argument(
        "ticker",
        nargs="?",
        default="AAPL",
        help="Stock ticker symbol (default: AAPL)",
    )
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()

    print(f"\nRunning analysis for {ticker}...\n")

    try:
        result = analyze_ticker(ticker)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except anthropic.AuthenticationError:
        print(
            "Error: Anthropic API key is missing or invalid.\n"
            "Set ANTHROPIC_API_KEY in your .env file or environment.",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as exc:
        logger.error("Unexpected error during analysis of %s: %s", ticker, exc, exc_info=True)
        print(
            f"Error: Unexpected failure analyzing {ticker}.\n"
            "Run with LOG_LEVEL=DEBUG for details.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"{'=' * 60}")
    print(f"  {result.company_name} ({result.ticker})")
    print(f"  Overall Score: {result.overall_score}/100")
    print(f"  Confidence: {result.confidence}")
    print(f"  Filing Date: {result.filing_date}")
    print(f"{'=' * 60}\n")

    print("PILLARS")
    print("-" * 40)
    for pillar in result.pillars:
        print(f"  {pillar.pillar_name:<20} {pillar.score:>3}/100")
        for metric in pillar.metrics:
            score = metric.normalized_score
            print(f"    ├ {metric.metric_name:<22} {score:>3}/100  [{metric.raw_value}]")
        if pillar.red_flags:
            for flag in pillar.red_flags:
                print(f"    ⚠  {flag}")

    print("\nGURU SCORECARDS")
    print("-" * 40)
    for guru in result.gurus:
        print(f"  {guru.guru_name:<22} {guru.score:>3}/100  → {guru.verdict}")
        print(f"    {guru.rationale[:120]}...")

    if result.errors:
        print("\nWARNINGS")
        for err in result.errors:
            print(f"  ⚠  {err}")

    output_path = f"output_{ticker}.json"
    with open(output_path, "w") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)
    print(f"\nFull JSON output written to {output_path}")


if __name__ == "__main__":
    main()
