"""Guru-specific entry price calculations.

Each of the 8 guru frameworks produces its own intrinsic value estimate
based on that guru's valuation philosophy. Fisher is excluded by design
(purely qualitative framework).
"""

from __future__ import annotations

import math
import logging

logger = logging.getLogger(__name__)

# Munger: quality deserves a fair multiple
_MUNGER_PE = 15.0

# Greenblatt: earnings yield threshold for a "magic formula" buy
_GREENBLATT_EARNINGS_YIELD = 0.12  # 12%

# Marks: only act at a significant margin of safety
_MARKS_DISCOUNT = 0.50

# Graham Number constant
_GRAHAM_CONSTANT = 22.5

# Smith: FCF yield threshold
_SMITH_FCF_YIELD = 0.10  # 10%

# Buffett: owner earnings yield × safety margin
_BUFFETT_OE_MULTIPLE = 10.0
_BUFFETT_SAFETY_MARGIN = 0.75


def calculate_guru_targets(metrics: dict) -> dict[str, float | None]:
    """Return a dict of {guru_name: target_price} for all 8 frameworks.

    Returns None for a guru when required inputs are missing or invalid.
    Inputs come from the precomputed metrics dict assembled in pipeline.py,
    which includes: trailing_eps, book_value, earnings_growth, current_price,
    fcf_per_share.
    """
    eps = metrics.get("trailing_eps")
    bvps = metrics.get("book_value")
    earnings_growth = metrics.get("earnings_growth")
    current_price = metrics.get("current_price")
    fcf_per_share = metrics.get("fcf_per_share")

    return {
        "buffett": _buffett_target(fcf_per_share),
        "munger": _munger_target(eps),
        "lynch": _lynch_target(eps, earnings_growth),
        "greenblatt": _greenblatt_target(eps),
        "marks": _marks_target(current_price),
        "graham": _graham_target(eps, bvps),
        "fisher": None,  # qualitative framework; no price target by design
        "smith": _smith_target(fcf_per_share),
    }


def _buffett_target(fcf_per_share: float | None) -> float | None:
    """(Owner Earnings per Share × 10) × 0.75 safety margin."""
    if fcf_per_share is None or fcf_per_share <= 0:
        return None
    return round(fcf_per_share * _BUFFETT_OE_MULTIPLE * _BUFFETT_SAFETY_MARGIN, 2)


def _munger_target(eps: float | None) -> float | None:
    """EPS × 15 — quality businesses deserve a fair multiple."""
    if eps is None or eps <= 0:
        return None
    return round(eps * _MUNGER_PE, 2)


def _lynch_target(eps: float | None, earnings_growth: float | None) -> float | None:
    """EPS × earnings_growth_as_percentage (PEG = 1 fair value).

    Growth expressed as a decimal (0.15 = 15%); Lynch fair P/E = growth %.
    Returns None when growth is absent or non-positive.
    """
    if eps is None or eps <= 0:
        return None
    if earnings_growth is None or earnings_growth <= 0:
        return None
    fair_pe = earnings_growth * 100.0
    return round(eps * fair_pe, 2)


def _greenblatt_target(eps: float | None) -> float | None:
    """Price where Earnings Yield = 12% → EPS / 0.12."""
    if eps is None or eps <= 0:
        return None
    return round(eps / _GREENBLATT_EARNINGS_YIELD, 2)


def _marks_target(current_price: float | None) -> float | None:
    """Marks demands a 50% discount to current price before acting."""
    if current_price is None or current_price <= 0:
        return None
    return round(current_price * _MARKS_DISCOUNT, 2)


def _graham_target(eps: float | None, bvps: float | None) -> float | None:
    """Graham Number = sqrt(22.5 × EPS × BVPS)."""
    if eps is None or bvps is None:
        return None
    if eps <= 0 or bvps <= 0:
        return None
    product = _GRAHAM_CONSTANT * eps * bvps
    return round(math.sqrt(product), 2)


def _smith_target(fcf_per_share: float | None) -> float | None:
    """Price where FCF Yield = 10% → FCF per Share / 0.10."""
    if fcf_per_share is None or fcf_per_share <= 0:
        return None
    return round(fcf_per_share / _SMITH_FCF_YIELD, 2)
