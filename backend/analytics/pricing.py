"""
EnergyPilot Canadian electricity pricing engine.

Responsibilities
----------------
- Normalize electricity readings.
- Normalize timestamps to the tariff timezone.
- Classify Ontario TOU and ULO pricing periods.
- Calculate Ontario TOU, ULO, and Tiered electricity supply costs.
- Produce dashboard-friendly pricing breakdowns.
- Compare pricing plans.
- Expose tariff/rate metadata.

Current supported market
------------------------
Canada
    └── Ontario
          └── Ontario Energy Board Regulated Price Plan
                ├── TOU
                ├── ULO
                └── Tiered

Important
---------
This module calculates the electricity supply / commodity component
represented by the configured RPP rates.

It does NOT calculate a complete utility bill.

Excluded components include:
- Delivery charges
- Regulatory charges
- HST
- Ontario Electricity Rebate
- Fixed monthly charges
- Utility-specific charges
- Retailer contract prices
- Other bill-level adjustments

Units
-----
Energy: kWh
Rate:   CAD/kWh
Cost:   CAD
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any
import math

import pandas as pd

from .pricing_config import (
    CANADIAN_PROVINCES,
    DEFAULT_COUNTRY,
    DEFAULT_CUSTOMER_TYPE,
    DEFAULT_PROVINCE,
    DEFAULT_TIMEZONE,
    ONTARIO_HOLIDAYS_2026,
    ONTARIO_RPP_EFFECTIVE_FROM,
    ONTARIO_RPP_EFFECTIVE_TO,
    ONTARIO_RPP_RATES,
    ONTARIO_TIER_THRESHOLDS,
    ONTARIO_TOU_SCHEDULE,
    ONTARIO_ULO_SCHEDULE,
    PROVINCE_TARIFFS,
)


# ============================================================================
# Constants
# ============================================================================

PLAN_TOU = "tou"
PLAN_TIERED = "tiered"
PLAN_ULO = "ulo"

SUPPORTED_PLANS = (
    PLAN_TOU,
    PLAN_TIERED,
    PLAN_ULO,
)

TOU_PERIODS = (
    "off_peak",
    "mid_peak",
    "on_peak",
)

ULO_PERIODS = (
    "weekend_off_peak",
    "overnight",
    "mid_peak",
    "on_peak",
)

CUSTOMER_RESIDENTIAL = "residential"
CUSTOMER_SMALL_BUSINESS = "small_business"

SUPPORTED_CUSTOMER_TYPES = (
    CUSTOMER_RESIDENTIAL,
    CUSTOMER_SMALL_BUSINESS,
)

DEFAULT_CURRENCY = "CAD"
DEFAULT_TARIFF_TIMEZONE = DEFAULT_TIMEZONE

EMPTY_COLUMNS = [
    "timestamp",
    "energy_kwh",
]

EFFECTIVE_FROM = date.fromisoformat(
    ONTARIO_RPP_EFFECTIVE_FROM
)

EFFECTIVE_TO = date.fromisoformat(
    ONTARIO_RPP_EFFECTIVE_TO
)


# ============================================================================
# Generic validation helpers
# ============================================================================

def _is_finite_number(value: Any) -> bool:
    """Return True if value can be safely interpreted as a finite number."""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _safe_non_negative_float(
    value: Any,
    default: float = 0.0,
) -> float:
    """Convert a value to a finite non-negative float."""
    if not _is_finite_number(value):
        return default

    return max(0.0, float(value))


def _normalize_plan(plan: str) -> str:
    """Normalize and validate a pricing plan."""
    normalized = str(plan).strip().lower()

    aliases = {
        "time_of_use": PLAN_TOU,
        "time-of-use": PLAN_TOU,
        "time of use": PLAN_TOU,
        "ultra_low_overnight": PLAN_ULO,
        "ultra-low-overnight": PLAN_ULO,
        "ultra low overnight": PLAN_ULO,
        "tier": PLAN_TIERED,
        "tiered_pricing": PLAN_TIERED,
        "tiered pricing": PLAN_TIERED,
    }

    normalized = aliases.get(
        normalized,
        normalized,
    )

    if normalized not in SUPPORTED_PLANS:
        raise ValueError(
            f"Unsupported pricing plan: {plan!r}. "
            f"Expected one of: {', '.join(SUPPORTED_PLANS)}."
        )

    return normalized


def _normalize_customer_type(customer_type: str) -> str:
    """Normalize and validate a customer type."""
    normalized = str(customer_type).strip().lower()

    aliases = {
        "home": CUSTOMER_RESIDENTIAL,
        "household": CUSTOMER_RESIDENTIAL,
        "residential_customer": CUSTOMER_RESIDENTIAL,
        "residential customer": CUSTOMER_RESIDENTIAL,
        "business": CUSTOMER_SMALL_BUSINESS,
        "small business": CUSTOMER_SMALL_BUSINESS,
        "small-business": CUSTOMER_SMALL_BUSINESS,
        "non-residential": CUSTOMER_SMALL_BUSINESS,
        "non_residential": CUSTOMER_SMALL_BUSINESS,
    }

    normalized = aliases.get(
        normalized,
        normalized,
    )

    if normalized not in SUPPORTED_CUSTOMER_TYPES:
        raise ValueError(
            f"Unsupported customer type: {customer_type!r}. "
            f"Expected one of: {', '.join(SUPPORTED_CUSTOMER_TYPES)}."
        )

    return normalized


def _normalize_province(province: str) -> str:
    """Normalize and validate a Canadian province/territory code."""
    normalized = str(province).strip().upper()

    if normalized not in CANADIAN_PROVINCES:
        raise ValueError(
            f"Unsupported Canadian province/territory: {province!r}. "
            f"Expected one of: {', '.join(CANADIAN_PROVINCES)}."
        )

    return normalized


def _normalize_timezone(timezone: str | None) -> str:
    """Return a usable tariff timezone."""
    return (
        str(timezone).strip()
        if timezone
        else DEFAULT_TARIFF_TIMEZONE
    )


# ============================================================================
# DataFrame normalization
# ============================================================================

def np_is_finite(series: pd.Series) -> pd.Series:
    """
    Vectorized finite-number validation.

    Invalid/non-numeric values are treated as False.
    """
    numeric = pd.to_numeric(
        series,
        errors="coerce",
    )

    return numeric.map(
        lambda value: (
            math.isfinite(float(value))
            if pd.notna(value)
            else False
        )
    )


def _empty_readings() -> pd.DataFrame:
    """Return an empty normalized readings DataFrame."""
    return pd.DataFrame(
        columns=EMPTY_COLUMNS
    )


def _coerce_timestamp(
    value: Any,
    timezone: str = DEFAULT_TARIFF_TIMEZONE,
) -> pd.Timestamp | None:
    """
    Parse one timestamp.

    Important behavior:
    - Naive timestamps are interpreted as local tariff time.
    - Timezone-aware timestamps are converted to tariff time.
    - Invalid timestamps return None.
    """
    if value is None or (
        isinstance(value, float)
        and math.isnan(value)
    ):
        return None

    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None

    if pd.isna(parsed):
        return None

    try:
        if parsed.tzinfo is None:
            return parsed.tz_localize(
                timezone
            )

        return parsed.tz_convert(
            timezone
        )
    except (TypeError, ValueError):
        return None


def _require_dataframe(
    df: pd.DataFrame,
    timezone: str = DEFAULT_TARIFF_TIMEZONE,
) -> pd.DataFrame:
    """
    Validate and normalize a pricing DataFrame.

    Required columns:
        timestamp
        energy_kwh

    Invalid timestamps and energy values are removed.

    Timestamp semantics are preserved correctly:
        naive -> interpreted in tariff timezone
        aware -> converted to tariff timezone
    """
    if df is None or df.empty:
        return _empty_readings()

    required_columns = {
        "timestamp",
        "energy_kwh",
    }

    missing = required_columns.difference(
        df.columns
    )

    if missing:
        raise ValueError(
            "Pricing data is missing required columns: "
            + ", ".join(sorted(missing))
        )

    result = df[
        [
            "timestamp",
            "energy_kwh",
        ]
    ].copy()

    tariff_timezone = _normalize_timezone(
        timezone
    )

    result["timestamp"] = result[
        "timestamp"
    ].map(
        lambda value: _coerce_timestamp(
            value,
            tariff_timezone,
        )
    )

    result["energy_kwh"] = pd.to_numeric(
        result["energy_kwh"],
        errors="coerce",
    )

    result = result.dropna(
        subset=[
            "timestamp",
            "energy_kwh",
        ]
    )

    result = result[
        np_is_finite(
            result["energy_kwh"]
        )
    ]

    result = result[
        result["energy_kwh"] >= 0
    ]

    return result.reset_index(
        drop=True
    )


def _normalize_readings(
    readings: Iterable[Any] | pd.DataFrame | None,
    timezone: str = DEFAULT_TARIFF_TIMEZONE,
) -> pd.DataFrame:
    """
    Convert supported reading formats into a normalized DataFrame.

    Supported:
    - pandas DataFrame
    - dictionaries
    - dataclass-like objects
    - ORM/database result objects
    """
    if readings is None:
        return _empty_readings()

    if isinstance(readings, pd.DataFrame):
        return _require_dataframe(
            readings,
            timezone,
        )

    rows: list[dict[str, Any]] = []

    for reading in readings:
        if isinstance(reading, Mapping):
            timestamp = reading.get(
                "timestamp"
            )

            if timestamp is None:
                timestamp = reading.get(
                    "ts"
                )

            energy = reading.get(
                "energy_kwh"
            )

            if energy is None:
                energy = reading.get(
                    "kwh"
                )

        else:
            timestamp = getattr(
                reading,
                "timestamp",
                None,
            )

            if timestamp is None:
                timestamp = getattr(
                    reading,
                    "ts",
                    None,
                )

            energy = getattr(
                reading,
                "energy_kwh",
                None,
            )

            if energy is None:
                energy = getattr(
                    reading,
                    "kwh",
                    None,
                )

        rows.append(
            {
                "timestamp": timestamp,
                "energy_kwh": energy,
            }
        )

    if not rows:
        return _empty_readings()

    return _require_dataframe(
        pd.DataFrame(rows),
        timezone,
    )


# ============================================================================
# Province / tariff configuration
# ============================================================================

def get_supported_provinces() -> dict[str, str]:
    """Return recognized Canadian provinces and territories."""
    return dict(
        CANADIAN_PROVINCES
    )


def is_province_supported(
    province: str,
) -> bool:
    """
    Return whether a verified pricing engine exists for a province.
    """
    normalized = _normalize_province(
        province
    )

    tariff = PROVINCE_TARIFFS.get(
        normalized
    )

    return bool(
        tariff
        and tariff.get("supported")
    )


def _get_province_tariff(
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    """Return verified tariff configuration for a province."""
    normalized = _normalize_province(
        province
    )

    tariff = PROVINCE_TARIFFS.get(
        normalized
    )

    if not tariff or not tariff.get(
        "supported"
    ):
        raise NotImplementedError(
            f"EnergyPilot does not yet have a verified pricing engine "
            f"for {CANADIAN_PROVINCES[normalized]} ({normalized}). "
            "Ontario is currently supported."
        )

    return tariff


def get_tariff_info(
    province: str = DEFAULT_PROVINCE,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
) -> dict[str, Any]:
    """
    Return frontend-friendly tariff metadata.
    """
    normalized_province = _normalize_province(
        province
    )

    normalized_customer = _normalize_customer_type(
        customer_type
    )

    tariff = _get_province_tariff(
        normalized_province
    )

    return {
        "country": tariff["country"],
        "province": tariff["province"],
        "province_name": tariff["province_name"],
        "market": tariff["market"],
        "program": tariff["program"],
        "currency": tariff["currency"],
        "timezone": tariff["timezone"],
        "customer_type": normalized_customer,
        "plans": list(
            tariff["plans"]
        ),
        "effective_from": tariff[
            "effective_from"
        ],
        "effective_to": tariff[
            "effective_to"
        ],
        "rates": {
            plan: dict(rates)
            for plan, rates in tariff[
                "rates"
            ].items()
        },
        "tier_thresholds": {
            customer: dict(thresholds)
            for customer, thresholds in tariff[
                "tier_thresholds"
            ].items()
        },
        "bill_components_included": [
            "electricity_supply_rate",
        ],
        "bill_components_not_included": [
            "delivery",
            "regulatory",
            "tax",
            "fixed_charges",
            "rebates",
            "utility_specific_charges",
        ],
    }


# ============================================================================
# Rate helpers
# ============================================================================

def _get_rate(
    plan: str,
    period: str,
    province: str = DEFAULT_PROVINCE,
) -> float:
    """
    Retrieve a configured rate in CAD/kWh.
    """
    normalized_plan = _normalize_plan(
        plan
    )

    normalized_province = _normalize_province(
        province
    )

    tariff = _get_province_tariff(
        normalized_province
    )

    rates = tariff.get(
        "rates",
        {}
    )

    plan_rates = rates.get(
        normalized_plan
    )

    if not isinstance(
        plan_rates,
        Mapping,
    ):
        raise ValueError(
            f"No rate configuration exists for "
            f"{normalized_province}/{normalized_plan}."
        )

    rate = plan_rates.get(
        period
    )

    if not _is_finite_number(rate):
        raise ValueError(
            f"Missing or invalid rate for "
            f"{normalized_province}/{normalized_plan}/{period}."
        )

    rate = float(rate)

    if rate < 0:
        raise ValueError(
            f"Electricity rate cannot be negative: "
            f"{normalized_province}/{normalized_plan}/{period}."
        )

    return rate


def get_rate_cents(
    plan: str,
    period: str,
    province: str = DEFAULT_PROVINCE,
) -> float:
    """Return a configured rate in cents/kWh."""
    return round(
        _get_rate(
            plan,
            period,
            province,
        ) * 100,
        4,
    )


# ============================================================================
# Timestamp / season handling
# ============================================================================

def _normalize_timestamp(
    timestamp: Any,
    timezone: str = DEFAULT_TARIFF_TIMEZONE,
) -> pd.Timestamp:
    """
    Normalize a timestamp to timezone-aware local tariff time.

    Naive timestamps are interpreted as local tariff time.

    Timezone-aware timestamps are converted to the tariff timezone.
    """
    normalized = _coerce_timestamp(
        timestamp,
        _normalize_timezone(timezone),
    )

    if normalized is None:
        raise ValueError(
            f"Invalid timestamp: {timestamp!r}"
        )

    return normalized


def tariff_season(
    timestamp: Any,
    timezone: str = DEFAULT_TARIFF_TIMEZONE,
) -> str:
    """
    Return Ontario's electricity pricing season.

    Summer:
        May 1 - October 31

    Winter:
        November 1 - April 30
    """
    local_time = _normalize_timestamp(
        timestamp,
        timezone,
    )

    if 5 <= local_time.month <= 10:
        return "summer"

    return "winter"


def _timestamp_date(
    timestamp: Any,
) -> date:
    """Return the local tariff calendar date."""
    return _normalize_timestamp(
        timestamp
    ).date()


# ============================================================================
# Ontario holiday handling
# ============================================================================

def _nth_weekday_of_month(
    year: int,
    month: int,
    weekday: int,
    occurrence: int,
) -> date:
    """
    Return the nth weekday of a month.

    weekday:
        Monday = 0
        Sunday = 6
    """
    if occurrence < 1:
        raise ValueError(
            "occurrence must be >= 1"
        )

    first = date(
        year,
        month,
        1,
    )

    offset = (
        weekday
        - first.weekday()
    ) % 7

    return first + timedelta(
        days=offset
        + (occurrence - 1) * 7
    )


def _calculate_easter(
    year: int,
) -> date:
    """Calculate Gregorian Easter Sunday."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3

    h = (
        19 * a
        + b
        - d
        - g
        + 15
    ) % 30

    i = c // 4
    k = c % 4

    l = (
        32
        + 2 * e
        + 2 * i
        - h
        - k
    ) % 7

    m = (
        a
        + 11 * h
        + 22 * l
    ) // 451

    month = (
        h
        + l
        - 7 * m
        + 114
    ) // 31

    day = (
        (
            h
            + l
            - 7 * m
            + 114
        )
        % 31
    ) + 1

    return date(
        year,
        month,
        day,
    )


def _apply_ontario_holiday_observation(
    holidays: dict[date, str],
) -> dict[date, str]:
    """
    Apply Ontario's weekend holiday observation rule.

    If a listed holiday falls on a weekend, the next weekday that is
    not already a holiday receives the holiday pricing.
    """
    result = dict(holidays)

    for holiday_date, holiday_name in list(
        holidays.items()
    ):
        if holiday_date.weekday() < 5:
            continue

        observed = holiday_date + timedelta(
            days=1
        )

        while (
            observed.weekday() >= 5
            or observed in result
        ):
            observed += timedelta(
                days=1
            )

        result[observed] = (
            f"{holiday_name} (observed)"
        )

    return result


def _canadian_ontario_holidays_for_year(
    year: int,
) -> dict[date, str]:
    """
    Return Ontario TOU/ULO holiday dates.

    The configured 2026 OEB dates are used directly.

    For other years, the recurring statutory holiday pattern is
    generated.
    """
    if year == 2026:
        return {
            date.fromisoformat(day): name
            for day, name in (
                ONTARIO_HOLIDAYS_2026.items()
            )
        }

    holidays: dict[date, str] = {}

    holidays[
        date(year, 1, 1)
    ] = "New Year's Day"

    holidays[
        _nth_weekday_of_month(
            year,
            2,
            0,
            3,
        )
    ] = "Family Day"

    easter = _calculate_easter(
        year
    )

    holidays[
        easter - timedelta(days=2)
    ] = "Good Friday"

    holidays[
        _nth_weekday_of_month(
            year,
            5,
            0,
            3,
        )
    ] = "Victoria Day"

    holidays[
        date(year, 7, 1)
    ] = "Canada Day"

    holidays[
        _nth_weekday_of_month(
            year,
            8,
            0,
            1,
        )
    ] = "Civic Holiday"

    holidays[
        _nth_weekday_of_month(
            year,
            9,
            0,
            1,
        )
    ] = "Labour Day"

    holidays[
        _nth_weekday_of_month(
            year,
            10,
            0,
            2,
        )
    ] = "Thanksgiving Day"

    holidays[
        date(year, 12, 25)
    ] = "Christmas Day"

    holidays[
        date(year, 12, 26)
    ] = "Boxing Day"

    return _apply_ontario_holiday_observation(
        holidays
    )


def is_ontario_holiday(
    timestamp: Any,
) -> bool:
    """Return whether a timestamp falls on an Ontario pricing holiday."""
    local_date = _timestamp_date(
        timestamp
    )

    return local_date in (
        _canadian_ontario_holidays_for_year(
            local_date.year
        )
    )


def holiday_name(
    timestamp: Any,
) -> str | None:
    """Return the Ontario pricing holiday name, if applicable."""
    local_date = _timestamp_date(
        timestamp
    )

    holidays = (
        _canadian_ontario_holidays_for_year(
            local_date.year
        )
    )

    return holidays.get(
        local_date
    )


# ============================================================================
# Schedule handling
# ============================================================================

def _period_from_schedule(
    timestamp: Any,
    schedule: Iterable[tuple[int, int, str]],
) -> str:
    """
    Find the pricing period for a local timestamp.

    Schedule entries use half-open intervals:
        start_hour <= hour < end_hour
    """
    local_time = _normalize_timestamp(
        timestamp
    )

    hour = local_time.hour

    for start_hour, end_hour, period in schedule:
        if start_hour <= hour < end_hour:
            return period

    raise RuntimeError(
        f"No pricing period matched timestamp: "
        f"{local_time.isoformat()}"
    )


# ============================================================================
# TOU classification
# ============================================================================

def tou_period(
    timestamp: Any,
) -> str:
    """
    Determine Ontario TOU pricing period.

    Weekends and OEB holidays are always off-peak.
    """
    local_time = _normalize_timestamp(
        timestamp
    )

    if is_ontario_holiday(
        local_time
    ):
        return "off_peak"

    if local_time.weekday() >= 5:
        return "off_peak"

    season = tariff_season(
        local_time
    )

    schedule = ONTARIO_TOU_SCHEDULE[
        season
    ][
        "weekday"
    ]

    return _period_from_schedule(
        local_time,
        schedule,
    )


# ============================================================================
# ULO classification
# ============================================================================

def ulo_period(
    timestamp: Any,
) -> str:
    """
    Determine Ontario ULO pricing period.

    ULO is year-round:

    Every day:
        23:00-07:00 -> overnight

    Weekends/holidays:
        07:00-23:00 -> weekend_off_peak

    Weekdays:
        07:00-16:00 -> mid_peak
        16:00-21:00 -> on_peak
        21:00-23:00 -> mid_peak
    """
    local_time = _normalize_timestamp(
        timestamp
    )

    if is_ontario_holiday(
        local_time
    ):
        schedule = ONTARIO_ULO_SCHEDULE[
            "holiday"
        ]

        return _period_from_schedule(
            local_time,
            schedule,
        )

    if local_time.weekday() >= 5:
        schedule = ONTARIO_ULO_SCHEDULE[
            "weekend"
        ]

        return _period_from_schedule(
            local_time,
            schedule,
        )

    schedule = ONTARIO_ULO_SCHEDULE[
        "weekday"
    ]

    return _period_from_schedule(
        local_time,
        schedule,
    )


# ============================================================================
# Period information
# ============================================================================

def get_period_info(
    timestamp: Any,
    plan: str = PLAN_TOU,
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    """
    Return frontend-friendly pricing-period information.
    """
    normalized_plan = _normalize_plan(
        plan
    )

    normalized_province = _normalize_province(
        province
    )

    local_time = _normalize_timestamp(
        timestamp
    )

    if normalized_plan == PLAN_TOU:
        period = tou_period(
            local_time
        )
    elif normalized_plan == PLAN_ULO:
        period = ulo_period(
            local_time
        )
    else:
        period = "tier_1"

    rate = _get_rate(
        normalized_plan,
        period,
        normalized_province,
    )

    return {
        "plan": normalized_plan,
        "period": period,
        "rate_cad_per_kwh": round(
            rate,
            6,
        ),
        "rate_cents_per_kwh": round(
            rate * 100,
            4,
        ),
        "currency": DEFAULT_CURRENCY,
        "timezone": DEFAULT_TARIFF_TIMEZONE,
        "local_timestamp": local_time.isoformat(),
        "date": local_time.date().isoformat(),
        "season": tariff_season(
            local_time
        ),
        "holiday": is_ontario_holiday(
            local_time
        ),
        "holiday_name": holiday_name(
            local_time
        ),
    }


# ============================================================================
# Cost calculation helpers
# ============================================================================

def _calculate_period_cost(
    df: pd.DataFrame,
    plan: str,
    province: str,
    classifier,
) -> float:
    """
    Generic cost calculation for time-based plans.
    """
    if df.empty:
        return 0.0

    total_cost = 0.0

    for row in df.itertuples(
        index=False
    ):
        period = classifier(
            row.timestamp
        )

        rate = _get_rate(
            plan,
            period,
            province,
        )

        total_cost += (
            float(row.energy_kwh)
            * rate
        )

    return float(
        total_cost
    )


# ============================================================================
# TOU cost
# ============================================================================

def calculate_tou(
    df: pd.DataFrame,
    province: str = DEFAULT_PROVINCE,
) -> float:
    """
    Calculate Ontario TOU electricity supply cost.

    Returns:
        CAD
    """
    normalized_province = _normalize_province(
        province
    )

    normalized = _require_dataframe(
        df
    )

    return _calculate_period_cost(
        normalized,
        PLAN_TOU,
        normalized_province,
        tou_period,
    )


# ============================================================================
# ULO cost
# ============================================================================

def calculate_ulo(
    df: pd.DataFrame,
    province: str = DEFAULT_PROVINCE,
) -> float:
    """
    Calculate Ontario ULO electricity supply cost.

    Returns:
        CAD
    """
    normalized_province = _normalize_province(
        province
    )

    normalized = _require_dataframe(
        df
    )

    return _calculate_period_cost(
        normalized,
        PLAN_ULO,
        normalized_province,
        ulo_period,
    )


# ============================================================================
# Tiered threshold helpers
# ============================================================================

def tier_period(
    timestamp: Any,
) -> str:
    """Return the Tiered pricing season."""
    return tariff_season(
        timestamp
    )


def get_tier_threshold(
    timestamp: Any,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
    province: str = DEFAULT_PROVINCE,
) -> float:
    """
    Return the monthly Tier 1 threshold in kWh.

    Ontario:
        Residential:
            Summer -> 600 kWh
            Winter -> 1000 kWh

        Small business:
            Year-round -> 750 kWh
    """
    normalized_customer = _normalize_customer_type(
        customer_type
    )

    normalized_province = _normalize_province(
        province
    )

    tariff = _get_province_tariff(
        normalized_province
    )

    thresholds = tariff.get(
        "tier_thresholds",
        {}
    )

    customer_thresholds = thresholds.get(
        normalized_customer
    )

    if not isinstance(
        customer_thresholds,
        Mapping,
    ):
        raise ValueError(
            f"No Tiered threshold configured for "
            f"{normalized_province}/{normalized_customer}."
        )

    season = tariff_season(
        timestamp
    )

    threshold = customer_thresholds.get(
        season
    )

    if not _is_finite_number(
        threshold
    ):
        raise ValueError(
            f"Invalid Tiered threshold for "
            f"{normalized_province}/"
            f"{normalized_customer}/"
            f"{season}."
        )

    threshold = float(
        threshold
    )

    if threshold < 0:
        raise ValueError(
            f"Tiered threshold cannot be negative: "
            f"{normalized_province}/"
            f"{normalized_customer}/"
            f"{season}."
        )

    return threshold


# ============================================================================
# Tiered cost
# ============================================================================

def _calculate_single_month_tiered_cost(
    month_df: pd.DataFrame,
    customer_type: str,
    province: str,
) -> dict[str, Any]:
    """
    Calculate Tiered pricing for one calendar month.

    Tier 1 resets at the beginning of each month.

    Note:
        Production utility billing should eventually use the actual
        billing-period start/end dates supplied by the utility rather
        than calendar months.
    """
    if month_df.empty:
        return {
            "total_kwh": 0.0,
            "tier_1_kwh": 0.0,
            "tier_2_kwh": 0.0,
            "tier_1_cost": 0.0,
            "tier_2_cost": 0.0,
            "total_cost": 0.0,
            "threshold_kwh": 0.0,
        }

    total_kwh = float(
        month_df["energy_kwh"].sum()
    )

    representative_timestamp = (
        month_df.iloc[0]["timestamp"]
    )

    threshold = get_tier_threshold(
        representative_timestamp,
        customer_type,
        province,
    )

    rate_1 = _get_rate(
        PLAN_TIERED,
        "tier_1",
        province,
    )

    rate_2 = _get_rate(
        PLAN_TIERED,
        "tier_2",
        province,
    )

    tier_1_kwh = min(
        total_kwh,
        threshold,
    )

    tier_2_kwh = max(
        total_kwh - threshold,
        0.0,
    )

    tier_1_cost = (
        tier_1_kwh
        * rate_1
    )

    tier_2_cost = (
        tier_2_kwh
        * rate_2
    )

    return {
        "total_kwh": total_kwh,
        "tier_1_kwh": tier_1_kwh,
        "tier_2_kwh": tier_2_kwh,
        "tier_1_cost": tier_1_cost,
        "tier_2_cost": tier_2_cost,
        "total_cost": (
            tier_1_cost
            + tier_2_cost
        ),
        "threshold_kwh": threshold,
    }


def _add_billing_month(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Add a YYYY-MM billing-month key using local tariff time."""
    result = df.copy()

    result["local_timestamp"] = (
        result["timestamp"]
        .map(
            _normalize_timestamp
        )
    )

    result["billing_month"] = (
        result["local_timestamp"]
        .map(
            lambda value: (
                value.year,
                value.month,
            )
        )
    )

    return result


def calculate_tiered(
    df: pd.DataFrame,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
    province: str = DEFAULT_PROVINCE,
) -> float:
    """
    Calculate Tiered electricity supply cost.

    The Tier 1 threshold resets every calendar month.
    """
    normalized = _require_dataframe(
        df
    )

    if normalized.empty:
        return 0.0

    normalized_customer = _normalize_customer_type(
        customer_type
    )

    normalized_province = _normalize_province(
        province
    )

    normalized = _add_billing_month(
        normalized
    )

    total_cost = 0.0

    for _, month_df in normalized.groupby(
        "billing_month",
        sort=True,
    ):
        result = _calculate_single_month_tiered_cost(
            month_df,
            normalized_customer,
            normalized_province,
        )

        total_cost += result[
            "total_cost"
        ]

    return float(
        total_cost
    )


# ============================================================================
# Tiered breakdown
# ============================================================================

def calculate_tiered_breakdown(
    readings: Iterable[Any] | pd.DataFrame | None,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    """Return a monthly Tiered pricing breakdown."""
    normalized_customer = _normalize_customer_type(
        customer_type
    )

    normalized_province = _normalize_province(
        province
    )

    df = _normalize_readings(
        readings
    )

    if df.empty:
        return {
            "plan": PLAN_TIERED,
            "customer_type": normalized_customer,
            "province": normalized_province,
            "months": [],
            "total_kwh": 0.0,
            "total_cost": 0.0,
        }

    df = _add_billing_month(
        df
    )

    rate_1 = _get_rate(
        PLAN_TIERED,
        "tier_1",
        normalized_province,
    )

    rate_2 = _get_rate(
        PLAN_TIERED,
        "tier_2",
        normalized_province,
    )

    months: list[dict[str, Any]] = []

    for month_key, month_df in df.groupby(
        "billing_month",
        sort=True,
    ):
        result = _calculate_single_month_tiered_cost(
            month_df,
            normalized_customer,
            normalized_province,
        )

        year, month_number = month_key

        month_label = (
            f"{year:04d}-{month_number:02d}"
        )

        months.append(
            {
                "month": month_label,
                "threshold_kwh": round(
                    result["threshold_kwh"],
                    3,
                ),
                "total_kwh": round(
                    result["total_kwh"],
                    3,
                ),
                "tier_1_kwh": round(
                    result["tier_1_kwh"],
                    3,
                ),
                "tier_2_kwh": round(
                    result["tier_2_kwh"],
                    3,
                ),
                "tier_1_rate": rate_1,
                "tier_1_rate_cents": round(
                    rate_1 * 100,
                    4,
                ),
                "tier_2_rate": rate_2,
                "tier_2_rate_cents": round(
                    rate_2 * 100,
                    4,
                ),
                "tier_1_cost": round(
                    result["tier_1_cost"],
                    2,
                ),
                "tier_2_cost": round(
                    result["tier_2_cost"],
                    2,
                ),
                "total_cost": round(
                    result["total_cost"],
                    2,
                ),
            }
        )

    return {
        "plan": PLAN_TIERED,
        "customer_type": normalized_customer,
        "province": normalized_province,
        "months": months,
        "total_kwh": round(
            sum(
                item["total_kwh"]
                for item in months
            ),
            3,
        ),
        "total_cost": round(
            sum(
                item["total_cost"]
                for item in months
            ),
            2,
        ),
    }


# ============================================================================
# Unified plan calculation
# ============================================================================

def calculate_plan_cost(
    df: pd.DataFrame,
    plan: str,
    province: str = DEFAULT_PROVINCE,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
) -> float:
    """Calculate electricity supply cost under a selected plan."""
    normalized_plan = _normalize_plan(
        plan
    )

    if normalized_plan == PLAN_TOU:
        return calculate_tou(
            df,
            province,
        )

    if normalized_plan == PLAN_ULO:
        return calculate_ulo(
            df,
            province,
        )

    if normalized_plan == PLAN_TIERED:
        return calculate_tiered(
            df,
            customer_type,
            province,
        )

    raise ValueError(
        f"Unsupported pricing plan: {plan!r}."
    )


def calculate_plan_costs(
    readings: Iterable[Any] | pd.DataFrame | None,
    province: str = DEFAULT_PROVINCE,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
) -> dict[str, float]:
    """
    Calculate costs for all supported plans.

    Returns:
        {
            "tou": ...,
            "tiered": ...,
            "ulo": ...
        }
    """
    normalized_province = _normalize_province(
        province
    )

    normalized_customer = _normalize_customer_type(
        customer_type
    )

    df = _normalize_readings(
        readings
    )

    if df.empty:
        return {
            plan: 0.0
            for plan in SUPPORTED_PLANS
        }

    return {
        plan: round(
            calculate_plan_cost(
                df,
                plan,
                normalized_province,
                normalized_customer,
            ),
            2,
        )
        for plan in SUPPORTED_PLANS
    }


# ============================================================================
# Time-based breakdown helper
# ============================================================================

def _calculate_period_breakdown(
    readings: Iterable[Any] | pd.DataFrame | None,
    plan: str,
    periods: tuple[str, ...],
    classifier,
    province: str,
) -> dict[str, Any]:
    """
    Generic breakdown generator for TOU/ULO.
    """
    normalized_province = _normalize_province(
        province
    )

    normalized_plan = _normalize_plan(
        plan
    )

    df = _normalize_readings(
        readings
    )

    breakdown: dict[str, dict[str, float]] = {}

    for period in periods:
        rate = _get_rate(
            normalized_plan,
            period,
            normalized_province,
        )

        breakdown[period] = {
            "energy_kwh": 0.0,
            "rate": rate,
            "rate_cents": round(
                rate * 100,
                4,
            ),
            "cost": 0.0,
        }

    if df.empty:
        return {
            "plan": normalized_plan,
            "province": normalized_province,
            "periods": breakdown,
            "total_kwh": 0.0,
            "total_cost": 0.0,
        }

    for row in df.itertuples(
        index=False
    ):
        period = classifier(
            row.timestamp
        )

        energy = float(
            row.energy_kwh
        )

        rate = breakdown[
            period
        ]["rate"]

        breakdown[
            period
        ]["energy_kwh"] += energy

        breakdown[
            period
        ]["cost"] += (
            energy * rate
        )

    total_kwh = sum(
        item["energy_kwh"]
        for item in breakdown.values()
    )

    total_cost = sum(
        item["cost"]
        for item in breakdown.values()
    )

    for item in breakdown.values():
        item["energy_kwh"] = round(
            item["energy_kwh"],
            3,
        )

        item["cost"] = round(
            item["cost"],
            2,
        )

    return {
        "plan": normalized_plan,
        "province": normalized_province,
        "periods": breakdown,
        "total_kwh": round(
            total_kwh,
            3,
        ),
        "total_cost": round(
            total_cost,
            2,
        ),
    }


def calculate_tou_breakdown(
    readings: Iterable[Any] | pd.DataFrame | None,
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    """Return a detailed TOU pricing breakdown."""
    return _calculate_period_breakdown(
        readings,
        PLAN_TOU,
        TOU_PERIODS,
        tou_period,
        province,
    )


def calculate_ulo_breakdown(
    readings: Iterable[Any] | pd.DataFrame | None,
    province: str = DEFAULT_PROVINCE,
) -> dict[str, Any]:
    """Return a detailed ULO pricing breakdown."""
    return _calculate_period_breakdown(
        readings,
        PLAN_ULO,
        ULO_PERIODS,
        ulo_period,
        province,
    )


# ============================================================================
# General pricing breakdown
# ============================================================================

def calculate_pricing_breakdown(
    readings: Iterable[Any] | pd.DataFrame | None,
    province: str = DEFAULT_PROVINCE,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
) -> dict[str, Any]:
    """
    Return all supported pricing breakdowns.

    Intended as a primary backend API response for EnergyPilot.
    """
    normalized_province = _normalize_province(
        province
    )

    normalized_customer = _normalize_customer_type(
        customer_type
    )

    df = _normalize_readings(
        readings
    )

    costs = calculate_plan_costs(
        df,
        normalized_province,
        normalized_customer,
    )

    return {
        "country": DEFAULT_COUNTRY,
        "province": normalized_province,
        "currency": DEFAULT_CURRENCY,
        "customer_type": normalized_customer,
        "plans": costs,
        "tou": calculate_tou_breakdown(
            df,
            normalized_province,
        ),
        "ulo": calculate_ulo_breakdown(
            df,
            normalized_province,
        ),
        "tiered": calculate_tiered_breakdown(
            df,
            normalized_customer,
            normalized_province,
        ),
    }


# ============================================================================
# Plan comparison
# ============================================================================

def compare_plans(
    readings: Iterable[Any] | pd.DataFrame | None,
    province: str = DEFAULT_PROVINCE,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
) -> dict[str, Any]:
    """
    Compare all supported plans.

    No lifestyle-based recommendation is made.
    """
    normalized_province = _normalize_province(
        province
    )

    normalized_customer = _normalize_customer_type(
        customer_type
    )

    df = _normalize_readings(
        readings
    )

    if df.empty:
        return {
            "province": normalized_province,
            "customer_type": normalized_customer,
            "currency": DEFAULT_CURRENCY,
            "costs": {
                plan: 0.0
                for plan in SUPPORTED_PLANS
            },
            "cheapest_plan": None,
            "most_expensive_plan": None,
            "spread": 0.0,
            "has_data": False,
        }

    costs = calculate_plan_costs(
        df,
        normalized_province,
        normalized_customer,
    )

    cheapest_plan = min(
        costs,
        key=lambda plan: (
            costs[plan],
            plan,
        ),
    )

    most_expensive_plan = max(
        costs,
        key=lambda plan: (
            costs[plan],
            plan,
        ),
    )

    minimum_cost = costs[
        cheapest_plan
    ]

    maximum_cost = costs[
        most_expensive_plan
    ]

    return {
        "province": normalized_province,
        "customer_type": normalized_customer,
        "currency": DEFAULT_CURRENCY,
        "costs": costs,
        "cheapest_plan": cheapest_plan,
        "most_expensive_plan": most_expensive_plan,
        "spread": round(
            maximum_cost - minimum_cost,
            2,
        ),
        "has_data": True,
    }


# ============================================================================
# Recommendation
# ============================================================================

def recommend_plan(
    readings: Iterable[Any] | pd.DataFrame | None,
    province: str = DEFAULT_PROVINCE,
    customer_type: str = DEFAULT_CUSTOMER_TYPE,
) -> dict[str, Any] | None:
    """
    Identify the mathematically lowest-cost electricity supply plan.

    This is a consumption-profile comparison, not a guarantee that a
    customer should switch plans.
    """
    normalized_province = _normalize_province(
        province
    )

    normalized_customer = _normalize_customer_type(
        customer_type
    )

    df = _normalize_readings(
        readings
    )

    if df.empty:
        return None

    costs = calculate_plan_costs(
        df,
        normalized_province,
        normalized_customer,
    )

    recommended_plan = min(
        costs,
        key=lambda plan: (
            costs[plan],
            plan,
        ),
    )

    lowest_cost = costs[
        recommended_plan
    ]

    highest_cost = max(
        costs.values()
    )

    return {
        "recommended_plan": recommended_plan,
        "costs": costs,
        "province": normalized_province,
        "customer_type": normalized_customer,
        "currency": DEFAULT_CURRENCY,
        "estimated_savings": round(
            max(
                0.0,
                highest_cost
                - lowest_cost,
            ),
            2,
        ),
        "recommendation_basis": (
            "Lowest calculated electricity "
            "supply cost for the supplied "
            "consumption profile."
        ),
        "warning": (
            "This is an electricity-rate comparison, "
            "not a complete utility bill comparison. "
            "Actual utility bills can include delivery, "
            "regulatory charges, taxes, rebates, fixed "
            "charges, and other utility-specific items."
        ),
    }


# ============================================================================
# Rate data status
# ============================================================================

def pricing_data_status(
    as_of: Any | None = None,
) -> dict[str, Any]:
    """
    Report whether a requested date falls inside the configured
    Ontario RPP rate period.
    """
    if as_of is None:
        requested_date = (
            datetime.now()
            .date()
        )
    elif isinstance(
        as_of,
        date,
    ) and not isinstance(
        as_of,
        datetime,
    ):
        requested_date = as_of
    else:
        requested_date = _normalize_timestamp(
            as_of
        ).date()

    if requested_date < EFFECTIVE_FROM:
        status = (
            "historical_before_configured_period"
        )
    elif requested_date <= EFFECTIVE_TO:
        status = (
            "published_current_period"
        )
    else:
        status = (
            "latest_known_rate_used"
        )

    return {
        "status": status,
        "requested_date": requested_date.isoformat(),
        "effective_from": EFFECTIVE_FROM.isoformat(),
        "effective_to": EFFECTIVE_TO.isoformat(),
        "province": DEFAULT_PROVINCE,
        "currency": DEFAULT_CURRENCY,
        "source": "Ontario Energy Board RPP",
        "rates_are_estimates_after_effective_to": (
            requested_date > EFFECTIVE_TO
        ),
        "note": (
            "For dates after the configured effective-to date, "
            "EnergyPilot uses the latest configured rates rather "
            "than inventing future rates."
        ),
    }


# ============================================================================
# Frontend formatting helpers
# ============================================================================

def format_rate(
    rate_cad_per_kwh: float,
) -> str:
    """Format a rate for frontend display."""
    if not _is_finite_number(
        rate_cad_per_kwh
    ):
        raise ValueError(
            f"Invalid electricity rate: "
            f"{rate_cad_per_kwh!r}"
        )

    return (
        f"${float(rate_cad_per_kwh):.3f}/kWh"
    )


def format_cost(
    cost_cad: float,
) -> str:
    """Format a CAD cost for frontend display."""
    if not _is_finite_number(
        cost_cad
    ):
        raise ValueError(
            f"Invalid cost: {cost_cad!r}"
        )

    return (
        f"${float(cost_cad):,.2f}"
    )


# ============================================================================
# Current configured Ontario rates
# ============================================================================

def _rate_metadata(
    plan: str,
    period: str,
) -> dict[str, float]:
    """Build frontend-friendly rate metadata from configuration."""
    rate = _get_rate(
        plan,
        period,
        DEFAULT_PROVINCE,
    )

    return {
        "cad_per_kwh": rate,
        "cents_per_kwh": round(
            rate * 100,
            4,
        ),
    }


def get_current_ontario_rates() -> dict[str, Any]:
    """
    Return the currently configured Ontario RPP rates.

    Values are derived from pricing_config.py rather than hard-coded
    separately in this module.
    """
    return {
        "province": DEFAULT_PROVINCE,
        "province_name": "Ontario",
        "country": DEFAULT_COUNTRY,
        "currency": DEFAULT_CURRENCY,
        "plans": {
            PLAN_TOU: {
                period: _rate_metadata(
                    PLAN_TOU,
                    period,
                )
                for period in TOU_PERIODS
            },
            PLAN_ULO: {
                period: _rate_metadata(
                    PLAN_ULO,
                    period,
                )
                for period in ULO_PERIODS
            },
            PLAN_TIERED: {
                period: _rate_metadata(
                    PLAN_TIERED,
                    period,
                )
                for period in (
                    "tier_1",
                    "tier_2",
                )
            },
        },
        "tier_thresholds": {
            customer: dict(
                thresholds
            )
            for customer, thresholds in (
                ONTARIO_TIER_THRESHOLDS.items()
            )
        },
        "effective_from": (
            ONTARIO_RPP_EFFECTIVE_FROM
        ),
        "effective_to": (
            ONTARIO_RPP_EFFECTIVE_TO
        ),
        "source": (
            "Ontario Energy Board "
            "Regulated Price Plan"
        ),
    }


# ============================================================================
# Public API
# ============================================================================

__all__ = [
    # Constants
    "PLAN_TOU",
    "PLAN_TIERED",
    "PLAN_ULO",
    "SUPPORTED_PLANS",
    "TOU_PERIODS",
    "ULO_PERIODS",
    "CUSTOMER_RESIDENTIAL",
    "CUSTOMER_SMALL_BUSINESS",
    "SUPPORTED_CUSTOMER_TYPES",

    # Province / tariff
    "get_supported_provinces",
    "is_province_supported",
    "get_tariff_info",
    "get_rate_cents",

    # Time / periods
    "tariff_season",
    "tou_period",
    "ulo_period",
    "tier_period",
    "is_ontario_holiday",
    "holiday_name",
    "get_period_info",

    # Tiered
    "get_tier_threshold",

    # Cost calculations
    "calculate_tou",
    "calculate_ulo",
    "calculate_tiered",
    "calculate_plan_cost",
    "calculate_plan_costs",

    # Breakdowns
    "calculate_tou_breakdown",
    "calculate_ulo_breakdown",
    "calculate_tiered_breakdown",
    "calculate_pricing_breakdown",

    # Comparison / recommendations
    "compare_plans",
    "recommend_plan",

    # Rate metadata
    "pricing_data_status",
    "get_current_ontario_rates",

    # Formatting
    "format_rate",
    "format_cost",

    # Data helpers
    "np_is_finite",
]