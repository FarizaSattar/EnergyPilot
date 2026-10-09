"""
Ontario electricity-rate calculations for EnergyPilot.

This module contains deterministic electricity pricing logic for Ontario
Regulated Price Plan (RPP) customers.

Supported plans
---------------
- Time-of-Use (TOU)
- Ultra-Low Overnight (ULO)
- Tiered

Important
---------
These rates represent the electricity-energy component of the RPP price.

They are NOT a complete electricity bill calculation.

A customer's actual bill can also contain items such as:
    - Ontario Electricity Rebate (OER), where applicable
    - delivery charges
    - regulatory charges
    - taxes
    - utility-specific charges

Keep those components separate from the energy-rate calculation.

Architecture
------------
    readings
       |
       v
    ontario_rates.py
       |
       +--> rate period
       +--> electricity cost
       +--> plan comparison
       |
       v
    recommendations.py
       |
       v
    context.py
       |
       v
    recommendation_service.py

The module deliberately contains no Flask, database, MQTT, React, or LLM
dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# =============================================================================
# Configuration
# =============================================================================

ONTARIO_TIMEZONE = "America/Toronto"

ONTARIO_ZONE = ZoneInfo(
    ONTARIO_TIMEZONE
)

OEB_SOURCE = (
    "Ontario Energy Board"
)

# Published RPP rate period represented by this configuration.
#
# The OEB changes RPP prices periodically. Keeping the effective date explicit
# prevents the application from presenting these numbers as timeless values.
RATES_EFFECTIVE_DATE = date(
    2025,
    11,
    1,
)

RATES_NEXT_REVIEW_DATE = date(
    2026,
    11,
    1,
)


# =============================================================================
# RPP rates
# =============================================================================

# Rates are stored internally as CAD per kWh.
#
# The OEB publishes the corresponding values as cents per kWh.
TOU_RATES_CAD_PER_KWH: dict[str, float] = {
    "off_peak": 0.098,
    "mid_peak": 0.157,
    "on_peak": 0.203,
}

ULO_RATES_CAD_PER_KWH: dict[str, float] = {
    "overnight": 0.039,
    "weekend_off_peak": 0.098,
    "mid_peak": 0.157,
    "on_peak": 0.391,
}

TIERED_RATES_CAD_PER_KWH: dict[str, float] = {
    "tier_1": 0.120,
    "tier_2": 0.142,
}


# =============================================================================
# Tier thresholds
# =============================================================================

# Residential customers have a seasonal threshold.
RESIDENTIAL_TIER_THRESHOLD_KWH = {
    "summer": 600.0,
    "winter": 1000.0,
}

# Small business / non-residential threshold.
NON_RESIDENTIAL_TIER_THRESHOLD_KWH = 750.0


# =============================================================================
# Holiday schedule
# =============================================================================

# These dates are maintained separately from the TOU period logic because
# statutory/observed holiday schedules are calendar rules, not clock rules.
#
# The OEB's 2026 schedule includes the following dates.
#
# If the application is used beyond this period, update this configuration
# from the OEB holiday schedule rather than silently assuming old dates remain
# valid.
ONTARIO_HOLIDAYS_2026 = frozenset(
    {
        date(2026, 1, 1),   # New Year's Day
        date(2026, 2, 16),  # Family Day
        date(2026, 4, 3),   # Good Friday
        date(2026, 5, 18),  # Victoria Day
        date(2026, 7, 1),   # Canada Day
        date(2026, 8, 3),   # Civic Holiday
        date(2026, 9, 7),   # Labour Day
        date(2026, 10, 12), # Thanksgiving Day
        date(2026, 12, 25), # Christmas Day
        date(2026, 12, 28), # Boxing Day
    }
)


# =============================================================================
# Public constants / compatibility
# =============================================================================

# Keep a simple TOU alias so existing code using `TOU["off_peak"]` continues
# to work. New code should prefer the explicit CAD-per-kWh name.
TOU = TOU_RATES_CAD_PER_KWH


# =============================================================================
# Exceptions
# =============================================================================

class OntarioRatesError(Exception):
    """Base exception for Ontario electricity-rate errors."""


class InvalidRateInputError(
    OntarioRatesError
):
    """Raised when an electricity-rate input is invalid."""


# =============================================================================
# Data model
# =============================================================================

@dataclass(frozen=True, slots=True)
class ElectricityRate:
    """
    One electricity price returned by the pricing layer.

    `rate_cad_per_kwh` is the canonical numerical representation.
    """

    plan: str
    period: str
    rate_cad_per_kwh: float
    effective_date: date = RATES_EFFECTIVE_DATE
    unit: str = "CAD/kWh"
    source: str = OEB_SOURCE

    @property
    def rate_cents_per_kwh(
        self,
    ) -> float:
        """Return the same rate in cents/kWh."""
        return (
            self.rate_cad_per_kwh * 100.0
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the rate for Flask/React consumers."""
        return {
            "plan": self.plan,
            "period": self.period,
            "rate": round(
                self.rate_cents_per_kwh,
                3,
            ),
            "rate_cad_per_kwh": round(
                self.rate_cad_per_kwh,
                5,
            ),
            "unit": "¢/kWh",
            "effective_date": (
                self.effective_date.isoformat()
            ),
            "source": self.source,
        }


# =============================================================================
# Validation
# =============================================================================

def _validate_finite_non_negative(
    value: Any,
    *,
    name: str,
) -> float:
    """Validate a numeric energy/rate input."""
    if isinstance(
        value,
        bool,
    ):
        raise InvalidRateInputError(
            f"{name} must be numeric."
        )

    try:
        number = float(value)
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise InvalidRateInputError(
            f"{name} must be numeric."
        ) from exc

    if not math.isfinite(number):
        raise InvalidRateInputError(
            f"{name} must be finite."
        )

    if number < 0:
        raise InvalidRateInputError(
            f"{name} cannot be negative."
        )

    return number


def _normalize_timestamp(
    timestamp: datetime | str,
) -> datetime:
    """
    Normalize timestamps to America/Toronto.

    Naive timestamps are interpreted as Ontario local time rather than UTC.
    This is intentional because TOU periods are defined using local time.
    """
    if isinstance(
        timestamp,
        str,
    ):
        value = timestamp.strip()

        if not value:
            raise InvalidRateInputError(
                "timestamp cannot be empty."
            )

        try:
            timestamp = datetime.fromisoformat(
                value.replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError as exc:
            raise InvalidRateInputError(
                f"Invalid timestamp: {value!r}"
            ) from exc

    if not isinstance(
        timestamp,
        datetime,
    ):
        raise InvalidRateInputError(
            "timestamp must be a datetime or ISO string."
        )

    if timestamp.tzinfo is None:
        # TOU schedules are local Ontario schedules. Treating a naive
        # timestamp as UTC would shift the price period for some readings.
        timestamp = timestamp.replace(
            tzinfo=ONTARIO_ZONE
        )

    return timestamp.astimezone(
        ONTARIO_ZONE
    )


def _normalize_plan(
    plan: str,
) -> str:
    """Normalize supported pricing-plan names."""
    if not isinstance(
        plan,
        str,
    ):
        raise InvalidRateInputError(
            "plan must be a string."
        )

    normalized = (
        plan.strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {
        "time_of_use": "tou",
        "timeofuse": "tou",
        "ultra_low_overnight": "ulo",
        "ultralowovernight": "ulo",
        "tier": "tiered",
    }

    normalized = aliases.get(
        normalized,
        normalized,
    )

    if normalized not in {
        "tou",
        "ulo",
        "tiered",
    }:
        raise InvalidRateInputError(
            "Unsupported plan. "
            "Expected 'tou', 'ulo', or 'tiered'."
        )

    return normalized


# =============================================================================
# Calendar helpers
# =============================================================================

def is_ontario_holiday(
    timestamp: datetime | str,
) -> bool:
    """
    Return whether the local Ontario date is an RPP holiday.

    The 2026 list is sourced from the OEB's published holiday schedule.
    """
    local_timestamp = _normalize_timestamp(
        timestamp
    )

    return (
        local_timestamp.date()
        in ONTARIO_HOLIDAYS_2026
    )


def is_summer(
    timestamp: datetime | str,
) -> bool:
    """
    Return whether a timestamp falls in the summer RPP period.

    Summer:
        May 1 through October 31

    Winter:
        November 1 through April 30
    """
    local_timestamp = _normalize_timestamp(
        timestamp
    )

    return 5 <= local_timestamp.month <= 10


def season_for_timestamp(
    timestamp: datetime | str,
) -> str:
    """Return 'summer' or 'winter'."""
    return (
        "summer"
        if is_summer(timestamp)
        else "winter"
    )


# =============================================================================
# TOU
# =============================================================================

def tou_period(
    timestamp: datetime | str,
) -> str:
    """
    Determine the Ontario TOU period for a timestamp.

    Summer weekday schedule:
        07:00–11:00  Mid-Peak
        11:00–17:00  On-Peak
        17:00–19:00  Mid-Peak
        19:00–07:00  Off-Peak

    Winter weekday schedule:
        07:00–11:00  On-Peak
        11:00–17:00  Mid-Peak
        17:00–19:00  On-Peak
        19:00–07:00  Off-Peak

    Weekends and OEB-designated holidays:
        Off-Peak all day
    """
    local_timestamp = _normalize_timestamp(
        timestamp
    )

    if (
        local_timestamp.weekday() >= 5
        or is_ontario_holiday(
            local_timestamp
        )
    ):
        return "off_peak"

    hour = local_timestamp.hour

    # Overnight period.
    if hour < 7 or hour >= 19:
        return "off_peak"

    if is_summer(
        local_timestamp
    ):
        # Summer weekday:
        # 7–11 mid, 11–17 on, 17–19 mid.
        if 7 <= hour < 11:
            return "mid_peak"

        if 11 <= hour < 17:
            return "on_peak"

        return "mid_peak"

    # Winter weekday:
    # 7–11 on, 11–17 mid, 17–19 on.
    if 7 <= hour < 11:
        return "on_peak"

    if 11 <= hour < 17:
        return "mid_peak"

    return "on_peak"


def get_tou_rate(
    timestamp: datetime | str,
) -> ElectricityRate:
    """Return the applicable TOU electricity rate."""
    period = tou_period(
        timestamp
    )

    return ElectricityRate(
        plan="TOU",
        period=period,
        rate_cad_per_kwh=TOU_RATES_CAD_PER_KWH[
            period
        ],
    )


def tou_cost(
    kwh: float,
    timestamp: datetime | str,
) -> float:
    """Calculate electricity-energy cost under TOU pricing."""
    energy = _validate_finite_non_negative(
        kwh,
        name="kwh",
    )

    rate = get_tou_rate(
        timestamp
    )

    return energy * rate.rate_cad_per_kwh


# =============================================================================
# ULO
# =============================================================================

def ulo_period(
    timestamp: datetime | str,
) -> str:
    """
    Determine the Ontario ULO period.

    Weekdays:
        23:00–07:00  Ultra-Low Overnight
        07:00–16:00  Mid-Peak
        16:00–21:00  On-Peak
        21:00–23:00  Mid-Peak

    Weekends / holidays:
        23:00–07:00  Ultra-Low Overnight
        07:00–23:00  Weekend Off-Peak
    """
    local_timestamp = _normalize_timestamp(
        timestamp
    )

    hour = local_timestamp.hour

    if hour >= 23 or hour < 7:
        return "overnight"

    if (
        local_timestamp.weekday() >= 5
        or is_ontario_holiday(
            local_timestamp
        )
    ):
        return "weekend_off_peak"

    if 7 <= hour < 16:
        return "mid_peak"

    if 16 <= hour < 21:
        return "on_peak"

    return "mid_peak"


def get_ulo_rate(
    timestamp: datetime | str,
) -> ElectricityRate:
    """Return the applicable ULO electricity rate."""
    period = ulo_period(
        timestamp
    )

    return ElectricityRate(
        plan="ULO",
        period=period,
        rate_cad_per_kwh=ULO_RATES_CAD_PER_KWH[
            period
        ],
    )


def ulo_cost(
    kwh: float,
    timestamp: datetime | str,
) -> float:
    """Calculate electricity-energy cost under ULO pricing."""
    energy = _validate_finite_non_negative(
        kwh,
        name="kwh",
    )

    rate = get_ulo_rate(
        timestamp
    )

    return energy * rate.rate_cad_per_kwh


# =============================================================================
# Tiered pricing
# =============================================================================

def tier_threshold(
    timestamp: datetime | str,
    *,
    customer_type: str = "residential",
) -> float:
    """
    Return the monthly Tier 1 threshold in kWh.

    Residential:
        Summer: 600 kWh/month
        Winter: 1000 kWh/month

    Non-residential:
        750 kWh/month
    """
    normalized_type = (
        customer_type
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    if normalized_type in {
        "residential",
        "household",
        "home",
    }:
        return RESIDENTIAL_TIER_THRESHOLD_KWH[
            season_for_timestamp(
                timestamp
            )
        ]

    if normalized_type in {
        "non_residential",
        "small_business",
        "business",
        "farm",
    }:
        return NON_RESIDENTIAL_TIER_THRESHOLD_KWH

    raise InvalidRateInputError(
        "Unsupported customer_type."
    )


def tiered_cost(
    monthly_kwh: float,
    timestamp: datetime | str | None = None,
    *,
    customer_type: str = "residential",
) -> float:
    """
    Calculate monthly Tiered electricity-energy cost.

    This function intentionally requires the monthly usage total because
    Tiered pricing is based on cumulative monthly consumption.

    `timestamp` determines the applicable seasonal threshold. If omitted,
    the current Ontario date is used.
    """
    usage = _validate_finite_non_negative(
        monthly_kwh,
        name="monthly_kwh",
    )

    if timestamp is None:
        timestamp = datetime.now(
            ONTARIO_ZONE
        )

    threshold = tier_threshold(
        timestamp,
        customer_type=customer_type,
    )

    first = min(
        usage,
        threshold,
    )

    second = max(
        0.0,
        usage - threshold,
    )

    return (
        first
        * TIERED_RATES_CAD_PER_KWH[
            "tier_1"
        ]
        + second
        * TIERED_RATES_CAD_PER_KWH[
            "tier_2"
        ]
    )


# =============================================================================
# Generic pricing API
# =============================================================================

def get_rate(
    plan: str,
    timestamp: datetime | str,
    *,
    customer_type: str = "residential",
) -> ElectricityRate:
    """
    Return the applicable rate for a plan and timestamp.

    Tiered pricing returns the Tier 1 rate because the actual tier depends
    on cumulative monthly consumption and cannot be determined from a
    timestamp alone.
    """
    normalized_plan = _normalize_plan(
        plan
    )

    if normalized_plan == "tou":
        return get_tou_rate(
            timestamp
        )

    if normalized_plan == "ulo":
        return get_ulo_rate(
            timestamp
        )

    # Tiered rate cannot be fully determined from time alone. Return Tier 1
    # as the base rate and expose the threshold separately through
    # tier_threshold().
    return ElectricityRate(
        plan="Tiered",
        period="tier_1",
        rate_cad_per_kwh=(
            TIERED_RATES_CAD_PER_KWH[
                "tier_1"
            ]
        ),
    )


def calculate_cost(
    kwh: float,
    timestamp: datetime | str,
    *,
    plan: str = "tou",
    customer_type: str = "residential",
) -> float:
    """
    Calculate electricity-energy cost for one interval.

    For TOU and ULO, the timestamp determines the rate.

    For Tiered pricing, use `tiered_cost()` with the complete monthly
    consumption because a single interval does not contain enough information
    to determine which tier applies.
    """
    normalized_plan = _normalize_plan(
        plan
    )

    if normalized_plan == "tou":
        return tou_cost(
            kwh,
            timestamp,
        )

    if normalized_plan == "ulo":
        return ulo_cost(
            kwh,
            timestamp,
        )

    raise InvalidRateInputError(
        "For Tiered pricing, use tiered_cost() "
        "with monthly_kwh."
    )


# =============================================================================
# Reading-based calculations
# =============================================================================

def estimate_tou(
    readings: Iterable[
        Mapping[str, Any]
    ],
) -> float:
    """
    Estimate total electricity-energy cost for readings under TOU.

    Accepted timestamp fields:
        timestamp
        ts

    Accepted energy field:
        energy_kwh
    """
    total_cost = 0.0

    for index, reading in enumerate(
        readings
    ):
        if not isinstance(
            reading,
            Mapping,
        ):
            raise InvalidRateInputError(
                f"Reading {index} must be a mapping."
            )

        timestamp = reading.get(
            "timestamp",
            reading.get("ts"),
        )

        if timestamp is None:
            raise InvalidRateInputError(
                f"Reading {index} has no timestamp."
            )

        energy = reading.get(
            "energy_kwh"
        )

        if energy is None:
            raise InvalidRateInputError(
                f"Reading {index} has no energy_kwh."
            )

        total_cost += tou_cost(
            energy,
            timestamp,
        )

    return total_cost


def estimate_ulo(
    readings: Iterable[
        Mapping[str, Any]
    ],
) -> float:
    """Estimate total electricity-energy cost under ULO pricing."""
    total_cost = 0.0

    for index, reading in enumerate(
        readings
    ):
        if not isinstance(
            reading,
            Mapping,
        ):
            raise InvalidRateInputError(
                f"Reading {index} must be a mapping."
            )

        timestamp = reading.get(
            "timestamp",
            reading.get("ts"),
        )

        energy = reading.get(
            "energy_kwh"
        )

        if timestamp is None:
            raise InvalidRateInputError(
                f"Reading {index} has no timestamp."
            )

        if energy is None:
            raise InvalidRateInputError(
                f"Reading {index} has no energy_kwh."
            )

        total_cost += ulo_cost(
            energy,
            timestamp,
        )

    return total_cost


# =============================================================================
# Plan comparison
# =============================================================================

def estimate_plan_costs(
    readings: Iterable[
        Mapping[str, Any]
    ],
    *,
    customer_type: str = "residential",
) -> dict[str, float]:
    """
    Estimate energy-component costs under TOU, ULO, and Tiered pricing.

    Important:
        Tiered pricing is evaluated by calendar month because its threshold
        applies to cumulative monthly consumption.

    The returned values are estimates of the electricity-energy component,
    not complete utility bills.
    """
    normalized_readings = []

    for index, reading in enumerate(
        readings
    ):
        if not isinstance(
            reading,
            Mapping,
        ):
            raise InvalidRateInputError(
                f"Reading {index} must be a mapping."
            )

        timestamp = reading.get(
            "timestamp",
            reading.get("ts"),
        )

        energy = reading.get(
            "energy_kwh"
        )

        if timestamp is None:
            raise InvalidRateInputError(
                f"Reading {index} has no timestamp."
            )

        energy = _validate_finite_non_negative(
            energy,
            name=f"reading[{index}].energy_kwh",
        )

        normalized_readings.append(
            (
                _normalize_timestamp(
                    timestamp
                ),
                energy,
            )
        )

    tou_total = 0.0
    ulo_total = 0.0
    tiered_total = 0.0

    # TOU and ULO are interval-based.
    for timestamp, energy in (
        normalized_readings
    ):
        tou_total += tou_cost(
            energy,
            timestamp,
        )

        ulo_total += ulo_cost(
            energy,
            timestamp,
        )

    # Tiered pricing must be calculated independently for each calendar
    # month. Applying one threshold to an entire multi-month dataset would
    # produce an incorrect estimate.
    monthly_usage: dict[
        tuple[int, int],
        float,
    ] = {}

    monthly_reference_timestamp: dict[
        tuple[int, int],
        datetime,
    ] = {}

    for timestamp, energy in (
        normalized_readings
    ):
        key = (
            timestamp.year,
            timestamp.month,
        )

        monthly_usage[key] = (
            monthly_usage.get(
                key,
                0.0,
            )
            + energy
        )

        monthly_reference_timestamp[
            key
        ] = timestamp

    for key, monthly_kwh in (
        monthly_usage.items()
    ):
        reference_timestamp = (
            monthly_reference_timestamp[
                key
            ]
        )

        tiered_total += tiered_cost(
            monthly_kwh,
            reference_timestamp,
            customer_type=customer_type,
        )

    return {
        "tou": round(
            tou_total,
            2,
        ),
        "ulo": round(
            ulo_total,
            2,
        ),
        "tiered": round(
            tiered_total,
            2,
        ),
    }


# =============================================================================
# Public rate snapshot
# =============================================================================

def get_current_electricity_rates() -> dict[str, Any]:
    """
    Return the configured RPP rate snapshot.

    The function name is retained for compatibility, but the returned
    effective date is explicit so callers can determine whether the local
    configuration needs to be refreshed.
    """
    return {
        "source": OEB_SOURCE,
        "effective_date": (
            RATES_EFFECTIVE_DATE.isoformat()
        ),

        "next_review_date": (
            RATES_NEXT_REVIEW_DATE.isoformat()
        ),

        "timezone": ONTARIO_TIMEZONE,

        "plans": {
            "tou": {
                period: round(
                    rate * 100,
                    3,
                )
                for period, rate in (
                    TOU_RATES_CAD_PER_KWH.items()
                )
            },

            "ulo": {
                period: round(
                    rate * 100,
                    3,
                )
                for period, rate in (
                    ULO_RATES_CAD_PER_KWH.items()
                )
            },

            "tiered": {
                period: round(
                    rate * 100,
                    3,
                )
                for period, rate in (
                    TIERED_RATES_CAD_PER_KWH.items()
                )
            },
        },

        "tier_thresholds_kwh": {
            "residential": {
                "summer": (
                    RESIDENTIAL_TIER_THRESHOLD_KWH[
                        "summer"
                    ]
                ),
                "winter": (
                    RESIDENTIAL_TIER_THRESHOLD_KWH[
                        "winter"
                    ]
                ),
            },
            "non_residential": (
                NON_RESIDENTIAL_TIER_THRESHOLD_KWH
            ),
        },

        "unit": "¢/kWh",

        "disclaimer": (
            "Electricity-energy component only; "
            "not a complete utility bill."
        ),
    }


# =============================================================================
# Compatibility aliases
# =============================================================================

def get_tou_period(
    timestamp: datetime | str,
) -> str:
    """Backward-compatible alias for tou_period()."""
    return tou_period(
        timestamp
    )


# =============================================================================
# Module exports
# =============================================================================

__all__ = [
    "ElectricityRate",
    "InvalidRateInputError",
    "ONTARIO_HOLIDAYS_2026",
    "ONTARIO_TIMEZONE",
    "TOU",
    "TOU_RATES_CAD_PER_KWH",
    "ULO_RATES_CAD_PER_KWH",
    "TIERED_RATES_CAD_PER_KWH",
    "calculate_cost",
    "estimate_plan_costs",
    "estimate_tou",
    "estimate_ulo",
    "get_current_electricity_rates",
    "get_rate",
    "get_tou_period",
    "get_tou_rate",
    "get_ulo_rate",
    "get_ulo_rate",
    "is_ontario_holiday",
    "is_summer",
    "season_for_timestamp",
    "tier_threshold",
    "tiered_cost",
    "tou_cost",
    "tou_period",
    "ulo_cost",
    "ulo_period",
]