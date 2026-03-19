"""Guru price target math validation.

Validates that get_all_price_targets() produces results that match
independently hand-calculated values for each of the 8 guru frameworks.

Sections:
  A  Fetch yfinance data + build enriched metrics dict (mirrors pipeline.py)
  B  Call get_all_price_targets() and print raw inputs
  C  Hand-calculate each guru target from the same inputs
  D  Compare system vs hand-calc (target, pct_away, in_zone)
  E  Print report table + write JSON artifact
  F  Edge case verification with synthetic metrics

Usage:
    .venv/bin/python validation/guru_targets_spot_check.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf

from services.guru_price_targets import calculate_guru_targets
from services.price_targets import get_all_price_targets

OUTPUT_PATH = Path(__file__).parent / "output" / "guru_targets_spot_check.json"

TICKERS = ["BBW", "AAPL", "DPZ"]

# PASS threshold: these are pure arithmetic formulas; any diff > 0.01% is a bug
TOLERANCE_PCT = 0.01

# Guru formulas documented here for reference (mirrors guru_price_targets.py)
GURU_FORMULAS = {
    "buffett":    "fcf_per_share × 10 × 0.75",
    "munger":     "trailing_eps × 15",
    "lynch":      "trailing_eps × (earnings_growth × 100)",
    "greenblatt": "trailing_eps / 0.12",
    "marks":      "current_price × 0.50",
    "graham":     "sqrt(22.5 × trailing_eps × book_value)",
    "smith":      "fcf_per_share / 0.10",
    "fisher":     "None (qualitative)",
}


# ── Section A: Fetch and enrich metrics ───────────────────────────────────────

def build_metrics(stock: yf.Ticker) -> tuple[dict, float]:
    """Replicate pipeline.py's metrics-enrichment step without running the
    full pipeline.  compute_all_metrics() is not needed here — the guru
    targets only depend on the 5 per-share/price fields added after it."""
    info = stock.info

    current_price = float(
        info.get("currentPrice") or info.get("regularMarketPrice") or 0
    )

    raw_fcf = info.get("freeCashflow")
    shares = info.get("sharesOutstanding")
    fcf_per_share = (
        float(raw_fcf) / float(shares)
        if raw_fcf and shares and float(shares) > 0
        else None
    )

    earnings_growth_raw = info.get("earningsGrowth") or info.get("revenueGrowth")

    metrics = {
        "current_price":  current_price if current_price > 0 else None,
        "trailing_eps":   info.get("trailingEps"),
        "book_value":     info.get("bookValue"),
        "fcf_per_share":  fcf_per_share,
        "earnings_growth": float(earnings_growth_raw) if earnings_growth_raw is not None else None,
    }

    return metrics, current_price


def print_inputs(ticker: str, metrics: dict) -> None:
    print(f"\n── Section A: Raw inputs ({ticker}) ───────────────────────────────────")
    for key, val in metrics.items():
        formatted = f"{val:.4f}" if isinstance(val, float) else str(val)
        print(f"  {key:<20} {formatted}")


# ── Section C: Hand-calculations ──────────────────────────────────────────────

def hand_calc_targets(metrics: dict) -> dict[str, float | None]:
    """Independent re-implementation of each guru formula.

    Must match guru_price_targets.py exactly, including the same guard
    conditions (≤ 0 → None) and rounding (round(..., 2)).
    """
    eps = metrics.get("trailing_eps")
    bvps = metrics.get("book_value")
    earnings_growth = metrics.get("earnings_growth")
    current_price = metrics.get("current_price")
    fcf_ps = metrics.get("fcf_per_share")

    def buffett() -> float | None:
        if fcf_ps is None or fcf_ps <= 0:
            return None
        return round(fcf_ps * 10.0 * 0.75, 2)

    def munger() -> float | None:
        if eps is None or eps <= 0:
            return None
        return round(eps * 15.0, 2)

    def lynch() -> float | None:
        if eps is None or eps <= 0:
            return None
        if earnings_growth is None or earnings_growth <= 0:
            return None
        fair_pe = earnings_growth * 100.0
        return round(eps * fair_pe, 2)

    def greenblatt() -> float | None:
        if eps is None or eps <= 0:
            return None
        return round(eps / 0.12, 2)

    def marks() -> float | None:
        if current_price is None or current_price <= 0:
            return None
        return round(current_price * 0.50, 2)

    def graham() -> float | None:
        if eps is None or bvps is None:
            return None
        if eps <= 0 or bvps <= 0:
            return None
        return round(math.sqrt(22.5 * eps * bvps), 2)

    def smith() -> float | None:
        if fcf_ps is None or fcf_ps <= 0:
            return None
        return round(fcf_ps / 0.10, 2)

    return {
        "buffett":    buffett(),
        "munger":     munger(),
        "lynch":      lynch(),
        "greenblatt": greenblatt(),
        "marks":      marks(),
        "graham":     graham(),
        "fisher":     None,
        "smith":      smith(),
    }


# ── Section D: Compare system vs hand-calc ────────────────────────────────────

def pct_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    if b == 0:
        return None if a == 0 else float("inf")
    return abs(a - b) / abs(b) * 100


def compare_targets(
    system_targets: dict,
    hand_targets: dict[str, float | None],
    current_price: float,
) -> list[dict]:
    rows = []
    by_guru = system_targets.get("by_guru", {})

    for guru in GURU_FORMULAS:
        sys_entry = by_guru.get(guru, {})
        sys_target = sys_entry.get("target")
        sys_pct_away = sys_entry.get("pct_away")
        sys_in_zone = sys_entry.get("in_zone")
        hand_target = hand_targets.get(guru)

        # Target comparison
        diff = pct_diff(sys_target, hand_target)
        both_none = sys_target is None and hand_target is None
        none_mismatch = (sys_target is None) != (hand_target is None)

        if both_none:
            target_pass = "N/A"
        elif none_mismatch:
            target_pass = "NONE-MISMATCH"
        elif diff is not None and diff <= TOLERANCE_PCT:
            target_pass = "PASS"
        else:
            target_pass = "FAIL"

        # pct_away and in_zone verification
        if hand_target is not None and current_price and current_price > 0:
            hand_pct_away = round((current_price - hand_target) / hand_target * 100.0, 1)
            hand_in_zone = current_price <= hand_target
            pct_away_match = sys_pct_away == hand_pct_away
            in_zone_match = sys_in_zone == hand_in_zone
        else:
            hand_pct_away = None
            hand_in_zone = None
            pct_away_match = sys_pct_away is None
            in_zone_match = sys_in_zone is None

        rows.append({
            "guru":            guru,
            "formula":         GURU_FORMULAS[guru],
            "system_target":   sys_target,
            "hand_target":     hand_target,
            "diff_pct":        diff,
            "target_pass":     target_pass,
            "sys_pct_away":    sys_pct_away,
            "hand_pct_away":   hand_pct_away,
            "pct_away_match":  pct_away_match,
            "sys_in_zone":     sys_in_zone,
            "hand_in_zone":    hand_in_zone,
            "in_zone_match":   in_zone_match,
        })

    return rows


# ── Section E: Report ─────────────────────────────────────────────────────────

def _fmt(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "None"
    return f"{v:.{decimals}f}"


def print_report(ticker: str, rows: list[dict]) -> None:
    header = (
        f"{'Guru':<12} {'System $':>9} {'Hand $':>9} {'Diff%':>7} "
        f"{'Target':>6} {'pct_away✓':>10} {'in_zone✓':>9} {'PASS':>5}"
    )
    sep = "─" * len(header)
    print(f"\n── Section E: Report ({ticker}) ────────────────────────────────────")
    print(sep)
    print(header)
    print(sep)

    for r in rows:
        all_pass = (
            r["target_pass"] in ("PASS", "N/A")
            and r["pct_away_match"]
            and r["in_zone_match"]
        )
        overall = "✅" if all_pass else "❌"
        target_flag = r["target_pass"]

        print(
            f"{r['guru']:<12} "
            f"{_fmt(r['system_target']):>9} "
            f"{_fmt(r['hand_target']):>9} "
            f"{_fmt(r['diff_pct'], 4):>7} "
            f"{target_flag:>6} "
            f"{'✓' if r['pct_away_match'] else '✗':>10} "
            f"{'✓' if r['in_zone_match'] else '✗':>9} "
            f"{overall:>5}"
        )

    print(sep)

    failures = [r for r in rows if r["target_pass"] not in ("PASS", "N/A")]
    pct_away_failures = [r for r in rows if not r["pct_away_match"]]
    in_zone_failures = [r for r in rows if not r["in_zone_match"]]

    if not failures and not pct_away_failures and not in_zone_failures:
        print(f"  ✓ All guru target checks PASSED for {ticker}")
    else:
        if failures:
            print(f"\n  ❌ Target failures:")
            for r in failures:
                print(f"     {r['guru']}: system={r['system_target']} hand={r['hand_target']} ({r['target_pass']})")
        if pct_away_failures:
            print(f"\n  ❌ pct_away mismatches:")
            for r in pct_away_failures:
                print(f"     {r['guru']}: system={r['sys_pct_away']} hand={r['hand_pct_away']}")
        if in_zone_failures:
            print(f"\n  ❌ in_zone mismatches:")
            for r in in_zone_failures:
                print(f"     {r['guru']}: system={r['sys_in_zone']} hand={r['hand_in_zone']}")


def ticker_has_failures(rows: list[dict]) -> bool:
    return any(
        r["target_pass"] not in ("PASS", "N/A")
        or not r["pct_away_match"]
        or not r["in_zone_match"]
        for r in rows
    )


# ── Section F: Edge case verification ─────────────────────────────────────────

def verify_edge_cases() -> list[dict]:
    """Run calculate_guru_targets() with synthetic metrics and assert expected Nones."""
    cases = [
        {
            "name": "eps=0 → Munger/Lynch/Greenblatt/Graham all None",
            "metrics": {"trailing_eps": 0, "book_value": 20.0, "earnings_growth": 0.15,
                        "current_price": 50.0, "fcf_per_share": 3.0},
            "expected_none": ["munger", "lynch", "greenblatt", "graham"],
            "expected_not_none": ["buffett", "marks", "smith"],
        },
        {
            "name": "bvps=-5 → Graham None",
            "metrics": {"trailing_eps": 2.0, "book_value": -5.0, "earnings_growth": 0.15,
                        "current_price": 50.0, "fcf_per_share": 3.0},
            "expected_none": ["graham"],
            "expected_not_none": ["munger", "lynch", "greenblatt", "buffett", "marks", "smith"],
        },
        {
            "name": "earnings_growth=-0.10 → Lynch None",
            "metrics": {"trailing_eps": 2.0, "book_value": 20.0, "earnings_growth": -0.10,
                        "current_price": 50.0, "fcf_per_share": 3.0},
            "expected_none": ["lynch"],
            "expected_not_none": ["munger", "greenblatt", "graham", "buffett", "marks", "smith"],
        },
        {
            "name": "fcf_per_share=0 → Buffett/Smith None",
            "metrics": {"trailing_eps": 2.0, "book_value": 20.0, "earnings_growth": 0.15,
                        "current_price": 50.0, "fcf_per_share": 0},
            "expected_none": ["buffett", "smith"],
            "expected_not_none": ["munger", "lynch", "greenblatt", "graham", "marks"],
        },
    ]

    results = []
    print("\n── Section F: Edge case verification ────────────────────────────────────")

    for case in cases:
        targets = calculate_guru_targets(case["metrics"])
        failures = []

        for guru in case["expected_none"]:
            if targets.get(guru) is not None:
                failures.append(f"{guru} should be None but got {targets[guru]}")

        for guru in case["expected_not_none"]:
            if targets.get(guru) is None:
                failures.append(f"{guru} should not be None but got None")

        passed = len(failures) == 0
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {case['name']}")
        for f in failures:
            print(f"         {f}")

        results.append({
            "case": case["name"],
            "passed": passed,
            "failures": failures,
            "targets": {k: v for k, v in targets.items()},
        })

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=== aEquity Guru Price Target Spot-Check ===")

    all_ticker_results = {}
    any_failure = False

    for ticker in TICKERS:
        print(f"\n{'═' * 60}")
        print(f"  Ticker: {ticker}")
        print(f"{'═' * 60}")

        print(f"Fetching yfinance data for {ticker}...")
        stock = yf.Ticker(ticker)
        metrics, current_price = build_metrics(stock)

        print_inputs(ticker, metrics)

        print(f"\n── Section B: Calling get_all_price_targets() ───────────────────────")
        system_targets = get_all_price_targets(metrics, current_price)
        by_guru = system_targets.get("by_guru", {})
        for guru, entry in by_guru.items():
            target = entry.get("target")
            pct_away = entry.get("pct_away")
            in_zone = entry.get("in_zone")
            print(f"  {guru:<12}  target={_fmt(target)}  pct_away={_fmt(pct_away, 1)}  in_zone={in_zone}")

        print(f"\n── Section C: Hand-calculating targets ──────────────────────────────")
        hand_targets = hand_calc_targets(metrics)
        for guru, val in hand_targets.items():
            print(f"  {guru:<12}  {_fmt(val)}")

        rows = compare_targets(system_targets, hand_targets, current_price)
        print_report(ticker, rows)

        if ticker_has_failures(rows):
            any_failure = True

        all_ticker_results[ticker] = {
            "metrics": {k: v for k, v in metrics.items()},
            "current_price": current_price,
            "rows": rows,
        }

    # Section F: edge cases (once, no network call)
    edge_case_results = verify_edge_cases()
    if any(not r["passed"] for r in edge_case_results):
        any_failure = True

    # Write JSON
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "tickers": all_ticker_results,
        "edge_cases": edge_case_results,
    }
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nJSON written → {OUTPUT_PATH}")

    if any_failure:
        print("\n❌ One or more checks FAILED — see details above.")
        sys.exit(1)
    else:
        print("\n✅ All guru target checks PASSED across all tickers and edge cases.")


if __name__ == "__main__":
    main()
