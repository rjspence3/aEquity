"""
BBW end-to-end math validation.

Sections:
  A  Fetch yfinance data + call compute_all_metrics()
  B  Independently hand-calculate all 23 metrics from raw statements
  C  Finviz cross-reference (best-effort; skipped if blocked)
  D  Grade verification via grade_metric()
  E  Report (stdout table + JSON output)

Usage:
    .venv/bin/python validation/bbw_spot_check.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf

from services.dimensions import DIMENSION_WEIGHTS, calculate_dimension_grades, calculate_overall_grade
from services.grader import Grade, aggregate_grades, grade_metric
from tools.calculator_tools import compute_all_metrics
from tools.metric_thresholds import THRESHOLDS, _GRADE_LEVELS

TICKER = "BBW"
OUTPUT_PATH = Path(__file__).parent / "output" / "bbw_spot_check.json"
TOLERANCE_PCT = 1.0  # flag discrepancies > 1%


# ── Section A: Fetch data ──────────────────────────────────────────────────────

def fetch_data(ticker: str) -> tuple[yf.Ticker, dict]:
    print(f"Fetching yfinance data for {ticker}...")
    stock = yf.Ticker(ticker)
    aequity = compute_all_metrics(stock)
    print(f"  compute_all_metrics() returned {sum(v is not None for v in aequity.values())}"
          f" / {len(aequity)} metrics")
    return stock, aequity


# ── Section B: Hand-calculations ──────────────────────────────────────────────
#
# These are independent re-implementations of the same formulas in
# calculator_tools.py.  Any divergence from aEquity values is a code bug.

def hand_calc_all(stock: yf.Ticker) -> dict[str, float | None]:
    inc = stock.income_stmt
    bal = stock.balance_sheet
    cf  = stock.cashflow
    info = stock.info

    results: dict[str, float | None] = {}

    # ── ROIC ──────────────────────────────────────────────────────────────────
    try:
        op_inc   = float(inc.loc["Operating Income"].iloc[0])
        tax_prov = float(inc.loc["Tax Provision"].iloc[0])
        pre_tax  = float(inc.loc["Pretax Income"].iloc[0])
        tax_rate = tax_prov / pre_tax
        nopat    = op_inc * (1 - tax_rate)
        ta       = float(bal.loc["Total Assets"].iloc[0])
        cl       = float(bal.loc["Current Liabilities"].iloc[0])
        cash     = float(bal.loc["Cash And Cash Equivalents"].iloc[0])
        ic       = ta - cl - cash
        results["roic"] = nopat / ic if ic > 0 else None
    except Exception as e:
        results["roic"] = None

    # ── FCF Conversion ────────────────────────────────────────────────────────
    try:
        fcf       = float(cf.loc["Free Cash Flow"].iloc[0])
        net_inc   = float(inc.loc["Net Income"].iloc[0])
        results["fcf_conversion"] = fcf / net_inc if net_inc > 0 else None
    except Exception:
        results["fcf_conversion"] = None

    # ── Net Debt / EBITDA ─────────────────────────────────────────────────────
    try:
        total_debt = 0.0
        for lbl in ["Total Debt", "Long Term Debt", "Short Long Term Debt"]:
            if lbl in bal.index:
                total_debt = float(bal.loc[lbl].iloc[0])
                break
        cash_val  = float(bal.loc["Cash And Cash Equivalents"].iloc[0])
        net_debt  = total_debt - cash_val

        if "EBITDA" in inc.index:
            ebitda = float(inc.loc["EBITDA"].iloc[0])
        else:
            oi = float(inc.loc["Operating Income"].iloc[0])
            da = 0.0
            if "Depreciation And Amortization" in inc.index:
                da = float(inc.loc["Depreciation And Amortization"].iloc[0])
            elif "Reconciled Depreciation" in inc.index:
                da = float(inc.loc["Reconciled Depreciation"].iloc[0])
            ebitda = oi + da

        results["net_debt_ebitda"] = net_debt / ebitda if ebitda > 0 else None
    except Exception:
        results["net_debt_ebitda"] = None

    # ── PEG Ratio (info pass-through) ─────────────────────────────────────────
    val = info.get("pegRatio")
    results["peg_ratio"] = float(val) if val is not None else None

    # ── Price/Book (info pass-through) ────────────────────────────────────────
    val = info.get("priceToBook")
    results["price_to_book"] = float(val) if val is not None else None

    # ── Current Ratio ─────────────────────────────────────────────────────────
    try:
        ca = float(bal.loc["Current Assets"].iloc[0])
        cl = float(bal.loc["Current Liabilities"].iloc[0])
        results["current_ratio"] = ca / cl if cl > 0 else None
    except Exception:
        results["current_ratio"] = None

    # ── Earnings Growth (info pass-through) ───────────────────────────────────
    val = info.get("earningsGrowth") or info.get("revenueGrowth")
    results["earnings_growth"] = float(val) if val is not None else None

    # ── ROE (info pass-through) ───────────────────────────────────────────────
    val = info.get("returnOnEquity")
    results["roe"] = float(val) if val is not None else None

    # ── ROA (info pass-through) ───────────────────────────────────────────────
    val = info.get("returnOnAssets")
    results["roa"] = float(val) if val is not None else None

    # ── ROCE ──────────────────────────────────────────────────────────────────
    try:
        ebit = float(inc.loc["Operating Income"].iloc[0])
        ta   = float(bal.loc["Total Assets"].iloc[0])
        cl   = float(bal.loc["Current Liabilities"].iloc[0])
        ce   = ta - cl
        results["roce"] = ebit / ce if ce > 0 else None
    except Exception:
        results["roce"] = None

    # ── Operating Margin (info pass-through) ──────────────────────────────────
    val = info.get("operatingMargins")
    results["operating_margin"] = float(val) if val is not None else None

    # ── Net Margin (info pass-through) ────────────────────────────────────────
    val = info.get("profitMargins")
    results["net_margin"] = float(val) if val is not None else None

    # ── Gross Margin (info pass-through) ──────────────────────────────────────
    val = info.get("grossMargins")
    results["gross_margin"] = float(val) if val is not None else None

    # ── ROIC v2 ───────────────────────────────────────────────────────────────
    try:
        op_inc = float(inc.loc["Operating Income"].iloc[0])
        nopat  = op_inc * 0.75

        total_debt = 0.0
        for lbl in ["Total Debt", "Long Term Debt"]:
            if lbl in bal.index:
                total_debt = float(bal.loc[lbl].iloc[0])
                break

        equity = None
        for lbl in ["Stockholders Equity", "Common Stock Equity",
                    "Total Equity Gross Minority Interest"]:
            if lbl in bal.index:
                equity = float(bal.loc[lbl].iloc[0])
                break

        cash = float(bal.loc["Cash And Cash Equivalents"].iloc[0])
        if equity is None:
            results["roic_v2"] = None
        else:
            ic = total_debt + equity - cash
            results["roic_v2"] = nopat / ic if ic > 0 else None
    except Exception:
        results["roic_v2"] = None

    # ── P/E Ratio (info pass-through) ─────────────────────────────────────────
    val = info.get("trailingPE")
    results["pe_ratio"] = float(val) if val is not None else None

    # ── Earnings Yield (derived) ──────────────────────────────────────────────
    pe = results.get("pe_ratio")
    results["earnings_yield"] = 1.0 / pe if pe and pe > 0 else None

    # ── FCF Yield ─────────────────────────────────────────────────────────────
    fcf_info  = info.get("freeCashflow")
    mktcap    = info.get("marketCap")
    results["fcf_yield"] = (float(fcf_info) / float(mktcap)
                            if fcf_info is not None and mktcap and float(mktcap) > 0
                            else None)

    # ── EV/FCF (info pass-through) ────────────────────────────────────────────
    val = info.get("enterpriseToFreeCashflow")
    results["ev_fcf"] = float(val) if val is not None else None

    # ── Debt/Equity ───────────────────────────────────────────────────────────
    try:
        total_debt = 0.0
        for lbl in ["Total Debt", "Long Term Debt"]:
            if lbl in bal.index:
                total_debt = float(bal.loc[lbl].iloc[0])
                break

        equity = None
        for lbl in ["Stockholders Equity", "Common Stock Equity",
                    "Total Equity Gross Minority Interest"]:
            if lbl in bal.index:
                equity = float(bal.loc[lbl].iloc[0])
                break

        results["debt_to_equity"] = (total_debt / equity
                                     if equity is not None and equity > 0
                                     else None)
    except Exception:
        results["debt_to_equity"] = None

    # ── Owner Earnings Yield ──────────────────────────────────────────────────
    try:
        net_inc = float(inc.loc["Net Income"].iloc[0])

        da = 0.0
        for lbl in ["Depreciation And Amortization", "Reconciled Depreciation"]:
            if lbl in inc.index:
                da = float(inc.loc[lbl].iloc[0])
                break
        if da == 0.0 and "Depreciation And Amortization" in cf.index:
            da = float(cf.loc["Depreciation And Amortization"].iloc[0])

        capex = 0.0
        for lbl in ["Capital Expenditure", "Capital Expenditures"]:
            if lbl in cf.index:
                capex = abs(float(cf.loc[lbl].iloc[0]))
                break

        oe     = net_inc + da - capex
        mktcap = info.get("marketCap")
        results["owner_earnings_yield"] = (oe / float(mktcap)
                                           if mktcap and float(mktcap) > 0
                                           else None)
    except Exception:
        results["owner_earnings_yield"] = None

    # ── Revenue Growth ────────────────────────────────────────────────────────
    try:
        for lbl in ["Total Revenue", "Operating Revenue"]:
            if lbl in inc.index:
                cur  = float(inc.loc[lbl].iloc[0])
                prev = float(inc.loc[lbl].iloc[1])
                results["revenue_growth"] = ((cur - prev) / abs(prev)
                                             if prev != 0 else None)
                break
        else:
            results["revenue_growth"] = None
    except Exception:
        results["revenue_growth"] = None

    # ── EPS Growth ────────────────────────────────────────────────────────────
    try:
        for lbl in ["Basic EPS", "Diluted EPS"]:
            if lbl in inc.index:
                cur  = float(inc.loc[lbl].iloc[0])
                prev = float(inc.loc[lbl].iloc[1])
                results["eps_growth"] = ((cur - prev) / abs(prev)
                                         if prev != 0 else None)
                break
        else:
            results["eps_growth"] = None
    except Exception:
        results["eps_growth"] = None

    # ── FCF Growth ────────────────────────────────────────────────────────────
    try:
        if "Free Cash Flow" in cf.index and cf.shape[1] >= 2:
            cur  = float(cf.loc["Free Cash Flow"].iloc[0])
            prev = float(cf.loc["Free Cash Flow"].iloc[1])
            results["fcf_growth"] = ((cur - prev) / abs(prev)
                                     if prev != 0 else None)
        else:
            results["fcf_growth"] = None
    except Exception:
        results["fcf_growth"] = None

    # Normalize any NaN to None (mirrors compute_all_metrics)
    return {k: (None if isinstance(v, float) and math.isnan(v) else v)
            for k, v in results.items()}


# ── Section B-audit: Raw-row audit trail ──────────────────────────────────────
#
# Shows which yfinance statement rows were actually used in each calculation.
# Detects label-drift: if yfinance renames a row, we'll see None here before
# the hand-calc comparison fails.

def audit_raw_rows(stock: yf.Ticker) -> dict[str, dict[str, str]]:
    """Return a dict of metric → {row_label: formatted_value} for each input row used."""
    inc = stock.income_stmt
    bal = stock.balance_sheet
    cf  = stock.cashflow

    def _get(df, label: str) -> str:
        try:
            val = float(df.loc[label].iloc[0])
            return f"${val / 1e6:.2f}M"
        except Exception:
            return "MISSING"

    def _first_found(df, labels: list[str]) -> tuple[str, str]:
        for label in labels:
            if label in df.index:
                return label, _get(df, label)
        return labels[0], "MISSING"

    audit: dict[str, dict[str, str]] = {}

    # ROIC
    debt_label, debt_val = _first_found(bal, ["Total Debt", "Long Term Debt", "Short Long Term Debt"])
    audit["roic"] = {
        "Operating Income (inc)":    _get(inc, "Operating Income"),
        "Tax Provision (inc)":       _get(inc, "Tax Provision"),
        "Pretax Income (inc)":       _get(inc, "Pretax Income"),
        "Total Assets (bal)":        _get(bal, "Total Assets"),
        "Current Liabilities (bal)": _get(bal, "Current Liabilities"),
        "Cash And Cash Equivalents (bal)": _get(bal, "Cash And Cash Equivalents"),
    }

    # FCF Conversion
    audit["fcf_conversion"] = {
        "Free Cash Flow (cf)": _get(cf, "Free Cash Flow"),
        "Net Income (inc)":    _get(inc, "Net Income"),
    }

    # Net Debt / EBITDA
    ebitda_label = "EBITDA" if "EBITDA" in inc.index else "derived (Operating Income + D&A)"
    da_label, da_val = _first_found(inc, ["Depreciation And Amortization", "Reconciled Depreciation"])
    audit["net_debt_ebitda"] = {
        f"{debt_label} (bal)":       debt_val,
        "Cash And Cash Equivalents (bal)": _get(bal, "Cash And Cash Equivalents"),
        f"EBITDA source: {ebitda_label}":  _get(inc, "EBITDA") if "EBITDA" in inc.index else (
            f"{_get(inc, 'Operating Income')} + {da_val}"
        ),
    }

    # ROCE
    audit["roce"] = {
        "Operating Income (inc)":    _get(inc, "Operating Income"),
        "Total Assets (bal)":        _get(bal, "Total Assets"),
        "Current Liabilities (bal)": _get(bal, "Current Liabilities"),
    }

    # Current Ratio
    audit["current_ratio"] = {
        "Current Assets (bal)":      _get(bal, "Current Assets"),
        "Current Liabilities (bal)": _get(bal, "Current Liabilities"),
    }

    # Debt/Equity
    eq_label, eq_val = _first_found(bal, ["Stockholders Equity", "Common Stock Equity",
                                           "Total Equity Gross Minority Interest"])
    audit["debt_to_equity"] = {
        f"{debt_label} (bal)": debt_val,
        f"{eq_label} (bal)":   eq_val,
    }

    # ROIC v2
    audit["roic_v2"] = {
        "Operating Income (inc)":    _get(inc, "Operating Income"),
        f"{debt_label} (bal)":       debt_val,
        f"{eq_label} (bal)":         eq_val,
        "Cash And Cash Equivalents (bal)": _get(bal, "Cash And Cash Equivalents"),
        "Tax assumption":            "25% flat rate",
    }

    # Revenue Growth
    rev_label, _ = _first_found(inc, ["Total Revenue", "Operating Revenue"])
    try:
        rev_curr = float(inc.loc[rev_label].iloc[0]) if rev_label in inc.index else None
        rev_prev = float(inc.loc[rev_label].iloc[1]) if rev_label in inc.index and inc.shape[1] >= 2 else None
        audit["revenue_growth"] = {
            f"{rev_label} current (inc)": f"${rev_curr / 1e6:.2f}M" if rev_curr else "MISSING",
            f"{rev_label} prior (inc)":   f"${rev_prev / 1e6:.2f}M" if rev_prev else "MISSING",
        }
    except Exception:
        audit["revenue_growth"] = {"status": "MISSING"}

    # EPS Growth
    eps_label, _ = _first_found(inc, ["Basic EPS", "Diluted EPS"])
    try:
        eps_curr = float(inc.loc[eps_label].iloc[0]) if eps_label in inc.index else None
        eps_prev = float(inc.loc[eps_label].iloc[1]) if eps_label in inc.index and inc.shape[1] >= 2 else None
        audit["eps_growth"] = {
            f"{eps_label} current (inc)": f"${eps_curr:.4f}" if eps_curr else "MISSING",
            f"{eps_label} prior (inc)":   f"${eps_prev:.4f}" if eps_prev else "MISSING",
        }
    except Exception:
        audit["eps_growth"] = {"status": "MISSING"}

    return audit


def print_audit(audit: dict[str, dict[str, str]]) -> None:
    print("\n── Raw-row audit trail ───────────────────────────────────────────────")
    for metric, rows in audit.items():
        print(f"  {metric}:")
        for label, val in rows.items():
            print(f"    {label:<45} {val}")


# ── Section C: Finviz cross-reference ─────────────────────────────────────────

FINVIZ_FIELD_MAP = {
    # finviz label → (aequity metric key, conversion fn)
    # Labels confirmed from live HTML 2026-03-18. Finviz uses full names in snapshot-td2.
    "ROE":          ("roe",              lambda s: float(s.strip("%")) / 100),
    "ROA":          ("roa",              lambda s: float(s.strip("%")) / 100),
    "ROIC":         ("roic",             lambda s: float(s.strip("%")) / 100),
    "Gross Margin": ("gross_margin",     lambda s: float(s.strip("%")) / 100),
    "Oper. Margin": ("operating_margin", lambda s: float(s.strip("%")) / 100),
    "Profit Margin":("net_margin",       lambda s: float(s.strip("%")) / 100),
    "P/E":          ("pe_ratio",         float),
    "P/B":          ("price_to_book",    float),
    "Current Ratio":("current_ratio",    float),
    "Debt/Eq":      ("debt_to_equity",   float),
}

# Known formula divergences between aEquity and Finviz — not bugs.
FINVIZ_DIVERGENCE_NOTES: dict[str, str] = {
    "roic": (
        "aEquity uses NOPAT/(Total Assets − CL − Cash); "
        "Finviz uses an equity-based formula. Divergence expected."
    ),
    "roa":  "Typically close; large diff suggests different averaging period.",
    "roe":  "Typically close; large diff suggests different averaging period.",
    "pe_ratio": "aEquity uses trailingPE; Finviz may use a slightly different price snapshot.",
    "debt_to_equity": "Finviz may include operating leases; aEquity uses Total Debt label priority.",
}


def fetch_finviz(ticker: str) -> dict[str, float | None]:
    import re
    import requests
    from bs4 import BeautifulSoup

    url = f"https://finviz.com/quote.ashx?t={ticker}&p=d"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  Finviz fetch failed: {e}")
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")

    # Finviz renders metrics in a table with cells containing the label and value
    data: dict[str, float | None] = {}
    cells = soup.find_all("td", class_=re.compile(r"snapshot-td2"))
    # Pairs: label cell followed by value cell
    texts = [c.get_text(strip=True) for c in cells]

    for label, (akey, convert) in FINVIZ_FIELD_MAP.items():
        try:
            idx = texts.index(label)
            raw_val = texts[idx + 1]
            if raw_val in ("-", "N/A", ""):
                data[akey] = None
            else:
                data[akey] = convert(raw_val)
        except (ValueError, IndexError, Exception):
            data[akey] = None

    found = sum(v is not None for v in data.values())
    print(f"  Finviz: parsed {found}/{len(FINVIZ_FIELD_MAP)} metrics")
    return data


# ── Section D: Grade verification ────────────────────────────────────────────

def verify_grades(aequity_metrics: dict[str, float | None]) -> dict[str, dict]:
    results = {}
    for metric_name, thresholds in THRESHOLDS.items():
        value = aequity_metrics.get(metric_name)
        pipeline_grade = grade_metric(metric_name, value)

        # Independent re-implementation of grade_metric logic
        if value is None:
            expected = Grade.INCOMPLETE
        else:
            higher = thresholds["higher_is_better"]
            expected = Grade.F
            for level in _GRADE_LEVELS:
                cutoff = thresholds[level]
                if higher and value >= cutoff:
                    expected = _level_str_to_grade(level)
                    break
                elif not higher and value <= cutoff:
                    expected = _level_str_to_grade(level)
                    break

        results[metric_name] = {
            "value": value,
            "pipeline_grade": pipeline_grade.value,
            "expected_grade": expected.value,
            "match": pipeline_grade == expected,
        }
    return results


def _level_str_to_grade(level: str) -> Grade:
    mapping = {
        "A_plus": Grade.A_PLUS, "A": Grade.A, "A_minus": Grade.A_MINUS,
        "B_plus": Grade.B_PLUS, "B": Grade.B, "B_minus": Grade.B_MINUS,
        "C_plus": Grade.C_PLUS, "C": Grade.C, "C_minus": Grade.C_MINUS,
        "D": Grade.D,
    }
    return mapping[level]


# ── Section E: Report ─────────────────────────────────────────────────────────

def pct_diff(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    if b == 0:
        return None if a == 0 else float("inf")
    return abs(a - b) / abs(b) * 100


def pass_fail(diff: float | None) -> str:
    if diff is None:
        return "N/A"
    return "PASS" if diff <= TOLERANCE_PCT else "FAIL"


def format_val(v: float | None, fmt: str = ".4f") -> str:
    if v is None:
        return "None"
    return format(v, fmt)


def print_report(
    aequity: dict[str, float | None],
    hand: dict[str, float | None],
    finviz: dict[str, float | None],
    grades: dict[str, dict],
) -> dict:
    all_metrics = sorted(set(aequity) | set(hand))

    rows = []
    for m in all_metrics:
        av  = aequity.get(m)
        hv  = hand.get(m)
        fv  = finviz.get(m)
        ah_diff = pct_diff(av, hv)
        af_diff = pct_diff(av, fv)
        gr  = grades.get(m, {})

        rows.append({
            "metric":           m,
            "aequity":          av,
            "hand":             hv,
            "finviz":           fv,
            "ah_diff_pct":      ah_diff,
            "af_diff_pct":      af_diff,
            "hand_pass":        pass_fail(ah_diff),
            "grade":            gr.get("pipeline_grade", "N/A"),
            "grade_verified":   gr.get("match", True),
        })

    # ── Console table ──────────────────────────────────────────────────────────
    header = (
        f"{'Metric':<26} {'aEquity':>12} {'Hand-calc':>12} {'Finviz':>10} "
        f"{'A↔H %':>7} {'Hand':>5} {'A↔F %':>7} {'Grade':>6} {'GradeOK':>8}"
    )
    sep = "─" * len(header)
    print(f"\n{sep}")
    print(header)
    print(sep)

    failures = []
    for r in rows:
        hand_flag = "⚠ " if r["hand_pass"] == "FAIL" else "  "
        grade_flag = "" if r["grade_verified"] else " ⚠"
        if r["hand_pass"] == "FAIL":
            failures.append(r["metric"])

        print(
            f"{hand_flag}{r['metric']:<24} "
            f"{format_val(r['aequity']):>12} "
            f"{format_val(r['hand']):>12} "
            f"{format_val(r['finviz'], '.3f'):>10} "
            f"{format_val(r['ah_diff_pct'], '.2f'):>7} "
            f"{r['hand_pass']:>5} "
            f"{format_val(r['af_diff_pct'], '.1f'):>7} "
            f"{r['grade']:>6}"
            f"{grade_flag}"
        )

    print(sep)

    total    = len(rows)
    n_pass   = sum(1 for r in rows if r["hand_pass"] == "PASS")
    n_na     = sum(1 for r in rows if r["hand_pass"] == "N/A")
    n_fail   = len(failures)
    grade_ok = sum(1 for r in grades.values() if r["match"])

    print(f"\nSummary:")
    print(f"  Hand-calc vs aEquity:  {n_pass} PASS / {n_fail} FAIL / {n_na} N/A (both None)")
    print(f"  Grade verification:    {grade_ok}/{len(grades)} correct")

    if failures:
        print(f"\n⚠  FAILURES (>1% discrepancy between aEquity and hand-calc):")
        for m in failures:
            r = next(x for x in rows if x["metric"] == m)
            print(f"   {m}: aEquity={format_val(r['aequity'])} hand={format_val(r['hand'])} diff={format_val(r['ah_diff_pct'], '.2f')}%")
    else:
        print("\n✓  All hand-calc checks PASSED (≤1% tolerance)")

    grade_failures = [m for m, g in grades.items() if not g["match"]]
    if grade_failures:
        print(f"\n⚠  GRADE MISMATCHES:")
        for m in grade_failures:
            g = grades[m]
            print(f"   {m}: pipeline={g['pipeline_grade']} expected={g['expected_grade']}")
    else:
        print("✓  All grade assignments verified")

    # ── Finviz divergence notes ────────────────────────────────────────────────
    finviz_divergent = []
    for r in rows:
        if r["af_diff_pct"] is not None and r["af_diff_pct"] > 5.0:
            finviz_divergent.append(r)

    if finviz_divergent:
        print(f"\nFinviz divergences >5% (expected — formula/period differences):")
        for r in finviz_divergent:
            note = FINVIZ_DIVERGENCE_NOTES.get(r["metric"], "Definition or time-period difference")
            print(f"   {r['metric']}: aEquity={format_val(r['aequity'])}"
                  f" Finviz={format_val(r['finviz'], '.4f')}"
                  f" diff={format_val(r['af_diff_pct'], '.1f')}%  — {note}")

    return {
        "ticker": TICKER,
        "total_metrics": total,
        "hand_pass": n_pass,
        "hand_fail": n_fail,
        "hand_na": n_na,
        "grade_correct": grade_ok,
        "grade_total": len(grades),
        "failures": failures,
        "grade_failures": grade_failures,
        "rows": rows,
    }


# ── Section F: Dimension grade verification ────────────────────────────────────
#
# calculate_dimension_grades() and calculate_overall_grade() are deterministic
# but have no test coverage. This section independently re-derives each
# dimension grade and compares against the pipeline's output.

# Maps each dimension to (metric_names, weights) — mirrors services/dimensions.py
_DIMENSION_SPEC: dict[str, tuple[list[str], list[float] | None]] = {
    "profitability":        (["roe", "roic", "net_margin"],            [0.40, 0.40, 0.20]),
    "moat":                 (["gross_margin", "operating_margin"],      [0.55, 0.45]),
    "balance_sheet":        (["debt_to_equity", "current_ratio"],       [0.55, 0.45]),
    "cash_flow":            (["fcf_yield", "fcf_conversion"],           [0.55, 0.45]),
    "valuation":            (["pe_ratio", "peg_ratio", "earnings_yield"],[0.35, 0.35, 0.30]),
    "growth":               (["revenue_growth", "eps_growth"],          [0.50, 0.50]),
    "management":           (["owner_earnings_yield"],                  None),
}


def _hand_earnings_consistency(metrics: dict[str, float | None]) -> Grade:
    """Mirror the non-standard earnings_consistency logic in dimensions.py."""
    eg = metrics.get("earnings_growth")
    if eg is None:
        return Grade.INCOMPLETE
    if eg >= 0.08:
        return grade_metric("earnings_growth", eg)
    if eg >= 0:
        return Grade.C
    return Grade.D


def verify_dimension_grades(aequity_metrics: dict[str, float | None]) -> dict:
    pipeline_dims = calculate_dimension_grades(aequity_metrics)
    pipeline_overall = calculate_overall_grade(pipeline_dims)

    rows = []
    all_match = True

    for dim, (metric_names, weights) in _DIMENSION_SPEC.items():
        grades = [grade_metric(name, aequity_metrics.get(name)) for name in metric_names]
        expected_grade = aggregate_grades(grades, weights=weights)
        pipeline_grade_str = pipeline_dims.get(dim, "INC")
        match = expected_grade.value == pipeline_grade_str
        if not match:
            all_match = False
        rows.append({
            "dimension": dim,
            "metrics":   ", ".join(metric_names),
            "pipeline":  pipeline_grade_str,
            "expected":  expected_grade.value,
            "match":     match,
        })

    # earnings_consistency uses custom logic
    expected_ec = _hand_earnings_consistency(aequity_metrics)
    pipeline_ec = pipeline_dims.get("earnings_consistency", "INC")
    ec_match = expected_ec.value == pipeline_ec
    if not ec_match:
        all_match = False
    rows.append({
        "dimension": "earnings_consistency",
        "metrics":   "earnings_growth (custom logic)",
        "pipeline":  pipeline_ec,
        "expected":  expected_ec.value,
        "match":     ec_match,
    })

    # Overall grade
    expected_grades_list = [
        aggregate_grades(
            [grade_metric(n, aequity_metrics.get(n)) for n in spec[0]],
            weights=spec[1],
        )
        for spec in _DIMENSION_SPEC.values()
    ] + [expected_ec]
    expected_weights = [DIMENSION_WEIGHTS[d] for d in _DIMENSION_SPEC] + [
        DIMENSION_WEIGHTS["earnings_consistency"]
    ]
    expected_overall = aggregate_grades(expected_grades_list, weights=expected_weights, min_coverage=0.60)

    print("\n── Section F: Dimension grade verification ───────────────────────────")
    hdr = f"  {'Dimension':<24} {'Metrics':<46} {'Pipeline':>9} {'Expected':>9} {'OK':>4}"
    print(hdr)
    print("  " + "─" * (len(hdr) - 2))
    for r in rows:
        flag = "✓" if r["match"] else "⚠"
        print(f"  {flag} {r['dimension']:<23} {r['metrics']:<46} {r['pipeline']:>9} {r['expected']:>9}")

    print(f"\n  Overall grade: pipeline={pipeline_overall.value}  expected={expected_overall.value}  "
          f"{'✓' if pipeline_overall == expected_overall else '⚠ MISMATCH'}")

    mismatches = [r["dimension"] for r in rows if not r["match"]]
    if not mismatches and pipeline_overall == expected_overall:
        print("  ✓ All dimension grades verified")
    else:
        if mismatches:
            print(f"  ⚠ Dimension mismatches: {mismatches}")
        if pipeline_overall != expected_overall:
            print(f"  ⚠ Overall grade mismatch")

    return {
        "dimensions": rows,
        "pipeline_overall": pipeline_overall.value,
        "expected_overall": expected_overall.value,
        "overall_match": pipeline_overall == expected_overall,
        "all_dimensions_match": all_match,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"=== aEquity BBW Spot-Check ===\n")

    # A: fetch
    stock, aequity = fetch_data(TICKER)

    # B: hand-calc
    print("Running hand-calculations...")
    hand = hand_calc_all(stock)
    print(f"  Hand-calc produced {sum(v is not None for v in hand.values())}"
          f"/{len(hand)} non-None values")

    # B-audit: raw-row audit trail
    print("Building raw-row audit trail...")
    audit = audit_raw_rows(stock)
    print_audit(audit)

    # C: Finviz
    print("Fetching Finviz data...")
    time.sleep(1)  # polite delay
    finviz = fetch_finviz(TICKER)

    # D: grades
    print("Verifying grade assignments...")
    grades = verify_grades(aequity)

    # E: report
    summary = print_report(aequity, hand, finviz, grades)

    # F: dimension grades
    print("Verifying dimension grades...")
    dim_summary = verify_dimension_grades(aequity)
    summary["dimension_verification"] = dim_summary

    # Write JSON
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary["raw_row_audit"] = audit
    with open(OUTPUT_PATH, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nJSON written → {OUTPUT_PATH}")

    # Exit 1 if any hand-calc failures or dimension mismatches
    if summary["failures"] or not dim_summary["all_dimensions_match"] or not dim_summary["overall_match"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
