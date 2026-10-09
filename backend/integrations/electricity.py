"""
Ontario electricity pricing for EnergyPilot.

This module contains the electricity-price data and tariff-period logic used
by the EnergyPilot pricing/recommendation layer.

Architecture:

    meter readings
          |
          v
    electricity.py
          |
          +--> identify TOU / ULO period
          |
          +--> return applicable electricity rate
          |
          +--> calculate energy cost
          |
          v
    pricing / recommendations
          |
          v
        Flask API
          |
          v
        React UI

Important:
    These are electricity supply prices under Ontario's Regulated Price Plan
    (RPP). They are NOT a complete residential electricity bill.

    A customer's total bill can also contain delivery, regulatory, taxes,
    rebates, and other charges. EnergyPilot should therefore describe these
    calculations as electricity-energy-cost estimates unless those additional
    components are explicitly modeled.

Source:
    Ontario Energy Board (OEB)

The OEB sets RPP rates annually. This module isolates the rate data so that
future rate changes can be updated in one place.

Current configured RPP period:
    Effective November 1, 2025

Rates:
    TOU:
        Off-peak:  9.8 ¢/kWh
        Mid-peak:  15.7 ¢/kWh
        On-peak:   20.3 ¢/kWh

    ULO:
        Overnight:       3.9 ¢/kWh
        Weekend offpeak: 9.8 ¢/kWh
        Mid-peak:       15.7 ¢/kWh
        On-peak:        39.1 ¢/kWh

    Tiered:
        Tier 1: 12.0 ¢/kWh
        Tier 2: 14.2 ¢/kWh

Reference:
    https://www.oeb.ca/consumer-information-and-protection/electricity-rates
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo


# =============================================================================
# Constants
# =============================================================================

ONTARIO_TIMEZONE = ZoneInfo("America/Toronto")

CENTS_PER_DOLLAR = 100.0

PLAN_TOU = "tou"
PLAN_ULO = "ulo"
PLAN_TIERED = "tiered"

VALID_PLANS = frozenset(
    {
        PLAN_TOU,
        PLAN_ULO,
        PLAN_TIERED,
    }
)

# OEB RPP prices effective November 1, 2025.
#
# Store rates internally as CAD/kWh rather than cents/kWh because cost
# calculations then become straightforward:
#
#     cost = energy_kwh * rate_cad_per_kwh
#
# The frontend can convert these values to ¢/kWh for display.
EFFECTIVE_DATE = date(2025, 11, 1)

TOU_RATES = {
    "off_peak": 0.098,
    "mid_peak": 0.157,
    "on_peak": 0.203,
}

ULO_RATES = {
    "overnight": 0.039,
    "weekend_off_peak": 0.098,
    "mid_peak": 0.157,
    "on_peak": 0.391,
}

TIERED_RATES = {
    "tier_1": 0.120,
    "tier_2": 0.142,
}

# Residential monthly thresholds.
#
# OEB:
#   Summer: May 1 - October 31 -> 600 kWh
#   Winter: November 1 - April 30 -> 1,000 kWh
RESIDENTIAL_TIER_THRESHOLDS_KWH = {
    "summer": 600.0,
    "winter": 1000.0,
}

# Small-business/non-residential RPP threshold.
NON_RESIDENTIAL_TIER_THRESHOLD_KWH = 750.0


# =============================================================================
# Data structures
# =============================================================================

@dataclass(frozen=True)
class ElectricityRate:
    """
    Normalized electricity rate returned by the pricing functions.

    rate_cad_per_kwh is the canonical numeric value used internally.
    rate_cents_per_kwh is provided for UI/API consumers.
    """

    plan: str
    period: str
    rate_cad_per_kwh: float
    effective_date: date
    source: str = "Ontario Energy Board"

    @property
    def rate_cents_per_kwh(self) -> float:
        """Return the rate in the unit commonly shown to consumers."""
        return self.rate_cad_per_kwh * CENTS_PER_DOLLAR

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        result = asdict(self)

        result["effective_date"] = self.effective_date.isoformat()
        result["rate_cents_per_kwh"] = self.rate_cents_per_kwh

        return result


# =============================================================================
# Validation
# =============================================================================

def _normalize_plan(plan: str) -> str:
    """Normalize and validate an electricity-price-plan identifier."""
    if not isinstance(plan, str):
        raise TypeError("plan must be a string.")

    normalized = plan.strip().lower()

    if normalized not in VALID_PLANS:
        raise ValueError(
            f"Unsupported electricity plan '{plan}'. "
            f"Expected one of: {', '.join(sorted(VALID_PLANS))}."
        )

    return normalized


def _validate_energy(energy_kwh: float) -> float:
    """Validate a non-negative energy quantity."""
    try:
        value = float(energy_kwh)
    except (TypeError, ValueError) as exc:
        raise ValueError("energy_kwh must be numeric.") from exc

    if value < 0:
        raise ValueError("energy_kwh cannot be negative.")

    return value


def _normalize_datetime(value: datetime | date) -> datetime:
    """
    Normalize a timestamp into Ontario local time.

    Naive timestamps are interpreted as America/Toronto because EnergyPilot's
    household tariff calculations are Ontario-local.
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)

    if not isinstance(value, datetime):
        raise TypeError(
            "timestamp must be a datetime or date."
        )

    if value.tzinfo is None:
        return value.replace(tzinfo=ONTARIO_TIMEZONE)

    return value.astimezone(ONTARIO_TIMEZONE)


def _season_for_date(value: date) -> Literal["summer", "winter"]:
    """
    Return the Ontario RPP season.

    Summer:
        May 1 through October 31

    Winter:
        November 1 through April 30
    """
    if 5 <= value.month <= 10:
        return "summer"

    return "winter"


# =============================================================================
# TOU periods
# =============================================================================

def get_tou_period(
    timestamp: datetime | date,
) -> str:
    """
    Determine the Ontario TOU period for a timestamp.

    TOU periods:

        Winter weekdays:
            07:00-11:00 -> on-peak
            11:00-17:00 -> mid-peak
            17:00-19:00 -> on-peak
            otherwise    -> off-peak

        Summer weekdays:
            07:00-11:00 -> mid-peak
            11:00-17:00 -> on-peak
            17:00-19:00 -> mid-peak
            otherwise    -> off-peak

        Weekends and holidays:
            off-peak all day

    Holiday handling is intentionally kept separate. This function handles
    weekdays/weekends; `get_tou_rate()` can be extended to receive an
    explicit holiday calendar.
    """
    local_dt = _normalize_datetime(timestamp)

    # Saturday = 5, Sunday = 6.
    if local_dt.weekday() >= 5:
        return "off_peak"

    current_time = local_dt.time()
    season = _season_for_date(local_dt.date())

    morning_start = time(7, 0)
    morning_end = time(11, 0)

    afternoon_end = time(17, 0)
    evening_end = time(19, 0)

    if season == "winter":
        if morning_start <= current_time < morning_end:
            return "on_peak"

        if morning_end <= current_time < afternoon_end:
            return "mid_peak"

        if afternoon_end <= current_time < evening_end:
            return "on_peak"

        return "off_peak"

    # Summer.
    if morning_start <= current_time < morning_end:
        return "mid_peak"

    if morning_end <= current_time < afternoon_end:
        return "on_peak"

    if afternoon_end <= current_time < evening_end:
        return "mid_peak"

    return "off_peak"


def get_tou_rate(
    timestamp: datetime | date,
) -> ElectricityRate:
    """Return the TOU electricity rate applicable at a timestamp."""
    period = get_tou_period(timestamp)

    return ElectricityRate(
        plan=PLAN_TOU,
        period=period,
        rate_cad_per_kwh=TOU_RATES[period],
        effective_date=EFFECTIVE_DATE,
    )


# =============================================================================
# ULO periods
# =============================================================================

def get_ulo_period(
    timestamp: datetime | date,
) -> str:
    """
    Determine the Ontario ULO period.

    ULO periods are year-round:

        Every day:
            23:00-07:00 -> overnight

        Weekends/holidays:
            07:00-23:00 -> weekend off-peak

        Weekdays:
            07:00-16:00 -> mid-peak
            16:00-21:00 -> on-peak
            21:00-23:00 -> mid-peak
    """
    local_dt = _normalize_datetime(timestamp)

    current_time = local_dt.time()

    overnight_start = time(23, 0)
    overnight_end = time(7, 0)

    # Overnight crosses midnight.
    if current_time >= overnight_start or current_time < overnight_end:
        return "overnight"

    if local_dt.weekday() >= 5:
        return "weekend_off_peak"

    if time(7, 0) <= current_time < time(16, 0):
        return "mid_peak"

    if time(16, 0) <= current_time < time(21, 0):
        return "on_peak"

    return "mid_peak"


def get_ulo_rate(
    timestamp: datetime | date,
) -> ElectricityRate:
    """Return the ULO electricity rate applicable at a timestamp."""
    period = get_ulo_period(timestamp)

    return ElectricityRate(
        plan=PLAN_ULO,
        period=period,
        rate_cad_per_kwh=ULO_RATES[period],
        effective_date=EFFECTIVE_DATE,
    )


# =============================================================================
# Tiered pricing
# =============================================================================

def get_tier_threshold(
    timestamp: datetime | date,
    *,
    customer_type: str = "residential",
) -> float:
    """
    Return the applicable monthly tier threshold in kWh.

    Residential:
        600 kWh summer
        1,000 kWh winter

    Non-residential:
        750 kWh year-round
    """
    local_dt = _normalize_datetime(timestamp)

    normalized_type = customer_type.strip().lower()

    if normalized_type in {
        "residential",
        "home",
        "household",
    }:
        season = _season_for_date(local_dt.date())
        return RESIDENTIAL_TIER_THRESHOLDS_KWH[season]

    if normalized_type in {
        "non_residential",
        "non-residential",
        "small_business",
        "small-business",
        "business",
    }:
        return NON_RESIDENTIAL_TIER_THRESHOLD_KWH

    raise ValueError(
        f"Unsupported customer_type '{customer_type}'."
    )


def get_tiered_rate(
    monthly_usage_kwh: float,
    timestamp: datetime | date,
    *,
    customer_type: str = "residential",
) -> ElectricityRate:
    """
    Return the Tiered rate applicable to the next kWh consumed.

    Important:
        Tiered pricing is monthly cumulative pricing. Unlike TOU and ULO,
        the timestamp alone cannot determine the applicable tier.

    For example, if a residential customer has already consumed 950 kWh in
    winter, the next 50 kWh are Tier 1 and usage beyond the 1,000 kWh
    threshold is Tier 2.
    """
    usage = _validate_energy(monthly_usage_kwh)

    threshold = get_tier_threshold(
        timestamp,
        customer_type=customer_type,
    )

    if usage < threshold:
        period = "tier_1"
        rate = TIERED_RATES["tier_1"]
    else:
        period = "tier_2"
        rate = TIERED_RATES["tier_2"]

    return ElectricityRate(
        plan=PLAN_TIERED,
        period=period,
        rate_cad_per_kwh=rate,
        effective_date=EFFECTIVE_DATE,
    )


# =============================================================================
# Generic rate lookup
# =============================================================================

def get_rate(
    timestamp: datetime | date,
    *,
    plan: str = PLAN_TOU,
    monthly_usage_kwh: float | None = None,
    customer_type: str = "residential",
) -> ElectricityRate:
    """
    Return the applicable electricity rate.

    Parameters
    ----------
    timestamp:
        Local or timezone-aware timestamp.

    plan:
        "tou", "ulo", or "tiered".

    monthly_usage_kwh:
        Required for Tiered pricing because the tier depends on cumulative
        monthly consumption.
    """
    normalized_plan = _normalize_plan(plan)

    if normalized_plan == PLAN_TOU:
        return get_tou_rate(timestamp)

    if normalized_plan == PLAN_ULO:
        return get_ulo_rate(timestamp)

    if monthly_usage_kwh is None:
        raise ValueError(
            "monthly_usage_kwh is required when using Tiered pricing."
        )

    return get_tiered_rate(
        monthly_usage_kwh,
        timestamp,
        customer_type=customer_type,
    )


# =============================================================================
# Cost calculations
# =============================================================================

def calculate_energy_cost(
    energy_kwh: float,
    rate_cad_per_kwh: float,
) -> float:
    """
    Calculate electricity-energy cost in CAD.

    This intentionally calculates only the electricity-energy component:

        kWh × CAD/kWh

    It does not include delivery, regulatory charges, taxes, rebates, or
    other bill components.
    """
    energy = _validate_energy(energy_kwh)

    try:
        rate = float(rate_cad_per_kwh)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "rate_cad_per_kwh must be numeric."
        ) from exc

    if rate < 0:
        raise ValueError(
            "rate_cad_per_kwh cannot be negative."
        )

    return energy * rate


def calculate_cost(
    energy_kwh: float,
    timestamp: datetime | date,
    *,
    plan: str = PLAN_TOU,
    monthly_usage_kwh: float | None = None,
    customer_type: str = "residential",
) -> float:
    """Calculate electricity-energy cost for a single interval."""
    rate = get_rate(
        timestamp,
        plan=plan,
        monthly_usage_kwh=monthly_usage_kwh,
        customer_type=customer_type,
    )

    return calculate_energy_cost(
        energy_kwh,
        rate.rate_cad_per_kwh,
    )


# =============================================================================
# Rate metadata / API helpers
# =============================================================================

def get_current_electricity_rates() -> dict[str, Any]:
    """
    Return the configured RPP electricity rates.

    The function name is retained for compatibility with existing EnergyPilot
    code, but "current" means the currently configured rate table in this
    application. It should be reviewed whenever the OEB publishes a new RPP
    period.
    """
    return {
        "source": "Ontario Energy Board",
        "effective_date": EFFECTIVE_DATE.isoformat(),
        "currency": "CAD",
        "unit": "¢/kWh",
        "plans": {
            PLAN_TOU: {
                period: period,
                "rate": rate * CENTS_PER_DOLLAR,
                "unit": "¢/kWh",
            }
            for period, rate in TOU_RATES.items()
        },
        "ulo": {
            period: {
                "period": period,
                "rate": rate * CENTS_PER_DOLLAR,
                "unit": "¢/kWh",
            }
            for period, rate in ULO_RATES.items()
        },
        "tiered": {
            period: {
                "period": period,
                "rate": rate * CENTS_PER_DOLLAR,
                "unit": "¢/kWh",
            }
            for period, rate in TIERED_RATES.items()
        },
        "tier_thresholds_kwh": {
            "residential": RESIDENTIAL_TIER_THRESHOLDS_KWH,
            "non_residential": NON_RESIDENTIAL_TIER_THRESHOLD_KWH,
        },
    }


def get_rate_snapshot(
    timestamp: datetime | date,
    *,
    plan: str = PLAN_TOU,
    monthly_usage_kwh: float | None = None,
    customer_type: str = "residential",
) -> dict[str, Any]:
    """
    Return the rate plus contextual metadata in API-friendly form.
    """
    rate = get_rate(
        timestamp,
        plan=plan,
        monthly_usage_kwh=monthly_usage_kwh,
        customer_type=customer_type,
    )

    return rate.to_dict()


# =============================================================================
# Public API
# =============================================================================

__all__ = [
    "CENTS_PER_DOLLAR",
    "EFFECTIVE_DATE",
    "ElectricityRate",
    "NON_RESIDENTIAL_TIER_THRESHOLD_KWH",
    "ONTARIO_TIMEZONE",
    "PLAN_TIERED",
    "PLAN_TOU",
    "PLAN_ULO",
    "RESIDENTIAL_TIER_THRESHOLDS_KWH",
    "TOU_RATES",
    "TIERED_RATES",
    "ULO_RATES",
    "calculate_cost",
    "calculate_energy_cost",
    "get_current_electricity_rates",
    "get_rate",
    "get_rate_snapshot",
    "get_tier_threshold",
    "get_tiered_rate",
    "get_tou_period",
    "get_tou_rate",
    "get_ulo_period",
    "get_ulo_rate",
]