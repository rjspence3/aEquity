"""Intrinsic value estimation and entry zone calculation.

Four independent valuation methods are averaged (excluding None) to produce
a fair value estimate. Five entry zones are derived from that estimate.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

# Entry zone multipliers relative to fair value
_ZONE_MUST_BUY = 0.65
_ZONE_COMPELLING = 0.75
_ZONE_ACCUMULATE = 0.85
_ZONE_FAIR_VALUE = 1.00
_ZONE_OVERVALUED = 1.20

# Assumptions used in owner earnings value
_OWNER_EARNINGS_MULTIPLE = 10.0  # FCF yield of 10% → P/FCF of 10x
_EARNINGS_POWER_PE = 15.0        # Graham's normalized P/E
_GRAHAM_CONSTANT = 22.5          # Graham Number constant


def _owner_earnings_value(metrics: dict[str, float | None]) -> float | None:
    """FCF-per-share × 10 (assumes a 10% FCF yield as fair value anchor).

    Derived from owner_earnings_yield: FV = 1 / owner_earnings_yield.
    Requires current_price from metrics to back-calculate per-share value.
    Falls back to fcf_yield if owner_earnings_yield is unavailable.
    """
    current_price = metrics.get("current_price")
    if current_price is None or current_price <= 0:
        return None

    oe_yield = metrics.get("owner_earnings_yield") or metrics.get("fcf_yield")
    if oe_yield and oe_yield > 0:
        # FV = current_price × (oe_yield / target_yield)
        # Using 6% as a target FCF yield for a quality business
        target_yield = 0.06
        return current_price * (oe_yield / target_yield)
    return None


def _lynch_value(metrics: dict[str, float | None]) -> float | None:
    """Peter Lynch PEG=1 fair value: EPS × expected growth rate.

    At PEG=1, fair P/E = growth rate (%). E.g., 15% grower → P/E of 15.
    FV = EPS × growth_rate_as_percentage
    """
    current_price = metrics.get("current_price")
    pe_ratio = metrics.get("pe_ratio")
    earnings_growth = metrics.get("earnings_growth") or metrics.get("eps_growth")

    if current_price is None or current_price <= 0:
        return None
    if pe_ratio is None or pe_ratio <= 0:
        return None
    if earnings_growth is None or earnings_growth <= 0:
        return None

    # EPS = current_price / pe_ratio
    eps = current_price / pe_ratio
    # Lynch fair P/E = growth rate as a percentage (15% growth → P/E 15)
    fair_pe = earnings_growth * 100.0
    return eps * fair_pe


def _graham_number_value(metrics: dict[str, float | None]) -> float | None:
    """Graham Number = sqrt(22.5 × EPS × Book Value Per Share).

    Requires trailingEps and bookValue from yfinance info dict. These are
    passed in via the extended metrics dict from compute_all_metrics().
    """
    eps = metrics.get("trailing_eps")
    bvps = metrics.get("book_value")

    if eps is None or bvps is None:
        return None
    if eps <= 0 or bvps <= 0:
        return None

    product = _GRAHAM_CONSTANT * eps * bvps
    return math.sqrt(product)


def _earnings_power_value(metrics: dict[str, float | None]) -> float | None:
    """Earnings Power Value = EPS × 15 (Graham's normalized P/E)."""
    current_price = metrics.get("current_price")
    pe_ratio = metrics.get("pe_ratio")

    if current_price is None or current_price <= 0:
        return None
    if pe_ratio is None or pe_ratio <= 0:
        return None

    eps = current_price / pe_ratio
    return eps * _EARNINGS_POWER_PE


def calculate_fair_value(metrics: dict[str, float | None]) -> dict | None:
    """
    Calculate intrinsic value from up to 4 methods and derive 5 entry zones.

    Returns None if no valuation method produces a result.

    Returns:
        {
            'methods': {
                'owner_earnings': float | None,
                'lynch': float | None,
                'graham': float | None,
                'earnings_power': float | None,
            },
            'fair_value': float,
            'zones': {
                'must_buy': float,     # 65% of fair value
                'compelling': float,   # 75%
                'accumulate': float,   # 85%
                'fair_value': float,   # 100%
                'overvalued': float,   # 120%
            },
            'methods_used': int,
        }
    """
    method_values = {
        "owner_earnings": _owner_earnings_value(metrics),
        "lynch": _lynch_value(metrics),
        "graham": _graham_number_value(metrics),
        "earnings_power": _earnings_power_value(metrics),
    }

    available = [v for v in method_values.values() if v is not None and v > 0]
    if not available:
        return None

    fair_value = sum(available) / len(available)

    return {
        "methods": method_values,
        "fair_value": round(fair_value, 2),
        "zones": {
            "must_buy":   round(fair_value * _ZONE_MUST_BUY, 2),
            "compelling": round(fair_value * _ZONE_COMPELLING, 2),
            "accumulate": round(fair_value * _ZONE_ACCUMULATE, 2),
            "fair_value": round(fair_value * _ZONE_FAIR_VALUE, 2),
            "overvalued": round(fair_value * _ZONE_OVERVALUED, 2),
        },
        "methods_used": len(available),
    }


def determine_price_zone(current_price: float, zones: dict[str, float]) -> str:
    """Return which entry zone the current price falls into.

    Zones (best to worst): must_buy → compelling → accumulate → fair_value → overvalued → above
    """
    if current_price <= zones["must_buy"]:
        return "must_buy"
    if current_price <= zones["compelling"]:
        return "compelling"
    if current_price <= zones["accumulate"]:
        return "accumulate"
    if current_price <= zones["fair_value"]:
        return "fair_value"
    if current_price <= zones["overvalued"]:
        return "above_fair_value"
    return "overvalued"
