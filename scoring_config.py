"""Tunable constants for scoring, normalization, and model selection.

All magic numbers that affect analysis results live here. Change these to
re-tune the scoring without touching calculation or pipeline logic.
"""

# ── Model IDs ─────────────────────────────────────────────────────────────────

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-5-20250929"

# ── Pillar weights ────────────────────────────────────────────────────────────
# Weights need not sum to 1.0 — they are normalised against whichever metrics
# are actually present, so missing data degrades gracefully.

ENGINE_WEIGHTS: dict[str, float] = {
    "ROIC": 0.60,
    "Gross Margin": 0.40,
}

FORTRESS_WEIGHTS: dict[str, float] = {
    "FCF Conversion": 0.40,
    "Net Debt / EBITDA": 0.40,
    "ROIC": 0.20,
}

ALIGNMENT_WEIGHTS: dict[str, float] = {
    "Insider Ownership": 0.50,
    "Shareholder Yield": 0.50,
}

# ── Verdict boundaries ────────────────────────────────────────────────────────
# Scores >= each boundary map to the corresponding verdict.

VERDICT_STRONG_BUY = 80
VERDICT_BUY = 65
VERDICT_HOLD = 45
VERDICT_AVOID = 30
# < VERDICT_AVOID → "Strong Avoid"

# ── Guru scoring weights ──────────────────────────────────────────────────────
# Each tuple is (weight, metric_key). Weights are normalised at runtime
# against whichever metrics are available.

BUFFETT_WEIGHTS = {
    "roic": 0.30,
    "fcf_conv": 0.25,
    "moat_score": 0.25,
    "nd_ebitda": 0.20,
}

LYNCH_WEIGHTS = {
    "peg": 0.40,
    "earnings_growth": 0.30,
    "understandability": 0.30,
}

GRAHAM_WEIGHTS = {
    "pb": 0.35,
    "current_ratio": 0.35,
    "earnings_growth": 0.30,
}

DAMODARAN_WEIGHTS = {
    "roic": 0.50,
    "peg": 0.30,
    "nd_ebitda": 0.20,
}

# ── Normalization ranges ──────────────────────────────────────────────────────
# (lower_bound, upper_bound) — score is 0 at lower, 100 at upper (linear).
# See calculator_tools.py for implementation.

ROIC_LOWER = 0.05   # 5%  → score 0
ROIC_UPPER = 0.20   # 20% → score 100

PEG_LOWER = 0.5     # ≤0.5 → score 100
PEG_UPPER = 2.5     # ≥2.5 → score 0

DEBT_LOWER = 1.0    # Net Debt/EBITDA ≤1 → score 100
DEBT_UPPER = 4.0    # Net Debt/EBITDA ≥4 → score 0

FCF_LOWER = 0.5     # FCF/Net Income ≤0.5 → score 0
FCF_UPPER = 1.2     # FCF/Net Income ≥1.2 → score 100

PB_LOWER = 1.5      # P/B ≤1.5 → score 100
PB_UPPER = 3.0      # P/B ≥3.0 → score 0

CURRENT_RATIO_LOWER = 1.0   # ≤1.0 → score 0
CURRENT_RATIO_UPPER = 2.0   # ≥2.0 → score 100

# Gross margin buckets (step function, not linear)
GROSS_MARGIN_TIER_HIGH = 0.60    # ≥60% (software/luxury) → 100
GROSS_MARGIN_TIER_MID_HIGH = 0.40  # 40-59% (consumer brands) → 75
GROSS_MARGIN_TIER_MID = 0.25     # 25-39% (industrial/healthcare) → 50
GROSS_MARGIN_TIER_LOW = 0.10     # 10-24% (retail/distribution) → 25
# <10% → 0

# ── Rate limiting ─────────────────────────────────────────────────────────────

MAX_ANALYSES_PER_HOUR = 20
