"""Review profiles: default conventions and thresholds for a kind of strategy.

A profile only fills values that rules.yaml does NOT declare; a declaration in rules.yaml always
wins. The values used, and where each came from (rules.yaml, profile or built-in default), are
listed in the report scope. The default profile does not presume any market calendar.
"""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "periods_per_year": 252,
    "stale_run": 10,  # identical consecutive closes that flag a frozen price
    "jump_threshold": 0.40,  # one-period absolute return that flags a price jump
    "rebalance_weight_tolerance": 0.10,  # relative deviation from 1/N tolerated
    "autocorrelation_max_lag": 10,
    "psr_threshold": 0.95,
    "dsr_threshold": 0.95,
    "pbo_threshold": 0.25,
}

PROFILES: dict[str, dict[str, Any]] = {
    "equities_daily": {
        "description": "Daily equity strategy. No market calendar presumed (declare conventions.calendar).",
        "conventions": {},
    },
    "nyse_equities_daily": {
        "description": "Daily US equity strategy on the NYSE calendar.",
        "conventions": {"calendar": "nyse"},
    },
    "byma_equities_daily": {
        "description": "Daily Argentine equity strategy on the BYMA calendar (check the holiday file).",
        "conventions": {"calendar": "byma"},
    },
    "equities_monthly": {
        "description": "Monthly-return strategy (12 periods per year, shorter frozen-price run).",
        "conventions": {"periods_per_year": 12, "stale_run": 3, "jump_threshold": 0.60},
    },
    "crypto_daily": {
        "description": "24x7 market: 365 periods per year and no trading-day requirement.",
        "conventions": {"periods_per_year": 365, "calendar": "none"},
    },
}
DEFAULT_PROFILE = "equities_daily"


def get_profile(name: str | None) -> dict[str, Any]:
    name = name or DEFAULT_PROFILE
    if name not in PROFILES:
        raise ValueError(f"unknown profile {name!r}; available: {', '.join(sorted(PROFILES))}")
    p = dict(PROFILES[name])
    p["name"] = name
    return p
