"""CLI entry point for single-stock analysis."""

import json
import sys

from pipeline import analyze_ticker


def main() -> None:
    ticker = sys.argv[1].strip().upper() if len(sys.argv) > 1 else "AAPL"

    print(f"\nRunning analysis for {ticker}...\n")

    result = analyze_ticker(ticker)

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

    # Write JSON output to file
    output_path = f"output_{ticker}.json"
    with open(output_path, "w") as f:
        json.dump(result.model_dump(mode="json"), f, indent=2, default=str)
    print(f"\nFull JSON output written to {output_path}")


if __name__ == "__main__":
    main()
