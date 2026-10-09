"""
EnergyPilot recommendation engine.

This module converts measured energy-use patterns into actionable
recommendations.

Responsibilities:
    - Analyze historical consumption patterns.
    - Identify meaningful load-shifting opportunities.
    - Compare modeled electricity pricing plans.
    - Incorporate household characteristics.
    - Estimate potential savings using explicit assumptions.
    - Assign recommendation priority.
    - Return a stable API-friendly recommendation schema.

Architecture:

    database.py
          │
          ▼
       readings
          │
          ├──────────────► analytics
          │
          ├──────────────► forecasting
          │
          ├──────────────► pricing
          │
          └──────────────► recommendations.py
                                  │
                                  ▼
                              app.py
                                  │
                                  ▼
                               React

Important:
    Recommendation logic belongs in the backend. React should display the
    recommendations it receives rather than independently calculating
    savings, thresholds, or tariff decisions.

Savings are estimates, not guarantees. They are intentionally based on
explicit assumptions defined in this module rather than pretending to know
the customer's actual retrofit cost, equipment efficiency, or future usage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import math

import pandas as pd

from analytics.pricing import (
    calculate_plan_costs,
    recommend_plan,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Usage thresholds are proportions of total consumption for the analyzed
# period. They are intentionally conservative so that recommendations are
# generated only when a meaningful pattern exists.

EVENING_START_HOUR = 17
EVENING_END_HOUR = 21

OVERNIGHT_START_HOUR = 0
OVERNIGHT_END_HOUR = 7

EVENING_USAGE_THRESHOLD = 0.20
OVERNIGHT_USAGE_THRESHOLD = 0.15

# Minimum amount of data required before usage-pattern recommendations are
# considered meaningful.
MIN_ANALYSIS_ROWS = 24

# Estimated savings assumptions.
#
# These are NOT claims about guaranteed savings. They are simple scenario
# assumptions used to communicate opportunity size in the portfolio demo.
LOAD_SHIFT_SAVINGS_RATE = 0.025
OVERNIGHT_SAVINGS_RATE = 0.018
HEAT_PUMP_EFFICIENCY_OPPORTUNITY = 0.08
HEAT_PUMP_ELECTRIFICATION_OPPORTUNITY = 0.05
INSULATION_OPPORTUNITY = 0.03
SMART_THERMOSTAT_OPPORTUNITY = 0.015

# Recommendation priorities.
PRIORITY_SCORES = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


PLAN_NAMES = {
    "tou": "Time-of-Use",
    "tiered": "Tiered",
    "ulo": "Ultra-Low Overnight",
}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _is_finite_number(
    value: Any,
) -> bool:
    """Return True when value can safely be represented as a finite float."""

    try:
        return math.isfinite(
            float(value)
        )
    except (TypeError, ValueError):
        return False


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    """Convert a value to a finite non-negative float."""

    if not _is_finite_number(value):
        return default

    return max(
        0.0,
        float(value),
    )


def _get_field(
    value: Any,
    field: str,
    default: Any = None,
) -> Any:
    """
    Read a field from either a mapping or an object.

    This keeps the recommendation engine compatible with dictionaries and
    dataclass-style EnergyReading objects.
    """

    if isinstance(value, Mapping):
        return value.get(
            field,
            default,
        )

    return getattr(
        value,
        field,
        default,
    )


# ---------------------------------------------------------------------------
# Reading preparation
# ---------------------------------------------------------------------------

def prepare_dataframe(
    readings: Iterable[Any] | None,
) -> pd.DataFrame:
    """
    Normalize historical readings for recommendation analysis.

    Invalid timestamps, non-numeric values, negative energy values, NaN, and
    infinite values are removed.

    Duplicate timestamps are preserved because multiple readings may represent
    different measurements within the same timestamp. The pricing service is
    responsible for its own aggregation semantics.
    """

    if readings is None:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "energy_kwh",
            ]
        )

    rows: list[dict[str, Any]] = []

    for reading in readings:
        rows.append(
            {
                "timestamp": _get_field(
                    reading,
                    "timestamp",
                ),
                "energy_kwh": _get_field(
                    reading,
                    "energy_kwh",
                ),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "energy_kwh",
            ]
        )

    df = pd.DataFrame(rows)

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce",
        utc=True,
    )

    df["energy_kwh"] = pd.to_numeric(
        df["energy_kwh"],
        errors="coerce",
    )

    df = df.dropna(
        subset=[
            "timestamp",
            "energy_kwh",
        ]
    )

    df = df[
        df["energy_kwh"] >= 0
    ]

    df = df[
        df["energy_kwh"].map(
            lambda value: math.isfinite(
                float(value)
            )
        )
    ]

    return (
        df.sort_values("timestamp")
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# Usage analysis
# ---------------------------------------------------------------------------

def calculate_usage_metrics(
    df: pd.DataFrame,
) -> dict[str, float]:
    """
    Calculate the usage metrics used by the recommendation engine.

    All percentages are fractions between 0 and 1.
    """

    if df.empty:
        return {
            "total_kwh": 0.0,
            "average_kwh": 0.0,
            "evening_kwh": 0.0,
            "overnight_kwh": 0.0,
            "evening_percentage": 0.0,
            "overnight_percentage": 0.0,
            "peak_hour_kwh": 0.0,
            "peak_hour": -1,
        }

    total_kwh = _safe_float(
        df["energy_kwh"].sum()
    )

    average_kwh = _safe_float(
        df["energy_kwh"].mean()
    )

    evening_mask = df[
        "timestamp"
    ].dt.hour.between(
        EVENING_START_HOUR,
        EVENING_END_HOUR,
        inclusive="left",
    )

    overnight_mask = df[
        "timestamp"
    ].dt.hour.between(
        OVERNIGHT_START_HOUR,
        OVERNIGHT_END_HOUR,
        inclusive="left",
    )

    evening_kwh = _safe_float(
        df.loc[
            evening_mask,
            "energy_kwh",
        ].sum()
    )

    overnight_kwh = _safe_float(
        df.loc[
            overnight_mask,
            "energy_kwh",
        ].sum()
    )

    denominator = max(
        total_kwh,
        1e-9,
    )

    evening_percentage = (
        evening_kwh / denominator
    )

    overnight_percentage = (
        overnight_kwh / denominator
    )

    hourly = (
        df.groupby(
            df["timestamp"].dt.hour
        )["energy_kwh"]
        .mean()
    )

    if hourly.empty:
        peak_hour = -1
        peak_hour_kwh = 0.0
    else:
        peak_hour = int(
            hourly.idxmax()
        )

        peak_hour_kwh = _safe_float(
            hourly.max()
        )

    return {
        "total_kwh": total_kwh,
        "average_kwh": average_kwh,
        "evening_kwh": evening_kwh,
        "overnight_kwh": overnight_kwh,
        "evening_percentage": evening_percentage,
        "overnight_percentage": overnight_percentage,
        "peak_hour_kwh": peak_hour_kwh,
        "peak_hour": peak_hour,
    }


# ---------------------------------------------------------------------------
# Household normalization
# ---------------------------------------------------------------------------

def normalize_household(
    household: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Normalize optional household information.

    Recommendations should remain functional when household information has
    not yet been configured.
    """

    if not isinstance(
        household,
        Mapping,
    ):
        return {}

    normalized = dict(
        household
    )

    for field in (
        "heating_type",
        "cooling_type",
        "home_type",
        "occupancy",
    ):
        value = normalized.get(
            field
        )

        if value is None:
            normalized[field] = ""
        else:
            normalized[field] = str(
                value
            ).strip()

    return normalized


def _normalized_text(
    value: Any,
) -> str:
    """Return a normalized lowercase text value."""

    return str(
        value or ""
    ).strip().lower()


# ---------------------------------------------------------------------------
# Savings estimation
# ---------------------------------------------------------------------------

def _estimate_monthly_usage(
    df: pd.DataFrame,
) -> float:
    """
    Estimate monthly energy consumption from the analyzed dataset.

    The calculation scales the observed consumption to a 30-day period.

    This is intentionally labeled as an estimate. A partial dataset should
    not be presented as an exact monthly bill.
    """

    if df.empty:
        return 0.0

    timestamps = df["timestamp"]

    start = timestamps.min()
    end = timestamps.max()

    elapsed_hours = max(
        (
            end - start
        ).total_seconds() / 3600.0,
        1.0,
    )

    observed_kwh = _safe_float(
        df["energy_kwh"].sum()
    )

    estimated_daily_kwh = (
        observed_kwh
        / max(
            elapsed_hours / 24.0,
            1.0 / 24.0,
        )
    )

    return max(
        0.0,
        estimated_daily_kwh * 30.0,
    )


def _estimate_savings(
    monthly_kwh: float,
    rate: float,
) -> float:
    """Estimate monthly savings using an explicit scenario percentage."""

    return round(
        max(
            0.0,
            monthly_kwh * rate,
        ),
        2,
    )


# ---------------------------------------------------------------------------
# Recommendation creation
# ---------------------------------------------------------------------------

def _make_recommendation(
    *,
    title: str,
    category: str,
    description: str,
    estimated_savings: float | None,
    priority: str,
    confidence: float,
    tags: list[str] | None = None,
    action: str | None = None,
) -> dict[str, Any]:
    """
    Construct the canonical recommendation response object.

    The frontend can consume this shape without needing to understand how the
    recommendation was generated.
    """

    normalized_priority = (
        str(priority)
        .strip()
        .lower()
    )

    if normalized_priority not in PRIORITY_SCORES:
        normalized_priority = "medium"

    confidence = min(
        1.0,
        max(
            0.0,
            float(confidence),
        ),
    )

    clean_tags = list(
        dict.fromkeys(
            str(tag).strip()
            for tag in (tags or [])
            if str(tag).strip()
        )
    )

    result = {
        "title": str(title).strip(),
        "category": str(category).strip(),
        "description": str(
            description
        ).strip(),
        "estimated_savings": (
            round(
                max(
                    0.0,
                    float(estimated_savings),
                ),
                2,
            )
            if estimated_savings is not None
            else None
        ),
        "priority": normalized_priority,
        "confidence": round(
            confidence,
            2,
        ),
        "tags": clean_tags[:5],
    }

    if action:
        result["action"] = str(
            action
        ).strip()

    return result


# ---------------------------------------------------------------------------
# Specific recommendation rules
# ---------------------------------------------------------------------------

def _rate_plan_recommendation(
    readings: Iterable[Any] | None,
) -> dict[str, Any] | None:
    """
    Compare modeled pricing plans.

    Only the modeled energy charge is compared. Fixed charges, taxes,
    delivery charges, eligibility requirements, and customer-specific
    conditions are outside this calculation unless explicitly included in
    pricing.py.
    """

    try:
        plan = recommend_plan(
            readings
        )
    except (
        ValueError,
        TypeError,
        KeyError,
    ):
        return None

    if not plan:
        return None

    recommended = plan.get(
        "recommended_plan"
    )

    if recommended not in PLAN_NAMES:
        return None

    costs = plan.get(
        "costs",
        {},
    )

    estimated_savings = _safe_float(
        plan.get(
            "estimated_savings"
        )
    )

    return _make_recommendation(
        title=(
            f"Review {PLAN_NAMES[recommended]} pricing"
        ),
        category="Rate Plan",
        description=(
            f"Based on the supplied consumption profile, "
            f"{PLAN_NAMES[recommended]} has the lowest modeled "
            f"energy charge among the plans currently configured "
            f"in EnergyPilot. This comparison does not represent "
            f"a complete utility bill."
        ),
        estimated_savings=estimated_savings,
        priority=(
            "high"
            if estimated_savings >= 10
            else "medium"
        ),
        confidence=0.90,
        tags=[
            "tariff",
            "cost",
            recommended,
        ],
        action=(
            "Compare your actual utility plan and eligibility "
            "before switching."
        ),
    )


def _evening_load_recommendation(
    metrics: Mapping[str, float],
    monthly_kwh: float,
) -> dict[str, Any] | None:
    """Generate a recommendation when evening usage is significant."""

    percentage = float(
        metrics["evening_percentage"]
    )

    if percentage <= EVENING_USAGE_THRESHOLD:
        return None

    savings = _estimate_savings(
        monthly_kwh,
        LOAD_SHIFT_SAVINGS_RATE,
    )

    return _make_recommendation(
        title="Shift flexible evening loads",
        category="Load Shifting",
        description=(
            f"Approximately {percentage:.0%} of the analyzed "
            "energy consumption occurs between 5 PM and 9 PM. "
            "Where practical, consider scheduling flexible loads "
            "such as laundry, dishwashing, or EV charging outside "
            "higher-cost periods."
        ),
        estimated_savings=savings,
        priority=(
            "high"
            if percentage >= 0.30
            else "medium"
        ),
        confidence=min(
            0.95,
            0.65 + percentage,
        ),
        tags=[
            "load shifting",
            "evening",
            "flexible loads",
        ],
        action=(
            "Review which evening loads can be scheduled automatically."
        ),
    )


def _overnight_recommendation(
    metrics: Mapping[str, float],
    monthly_kwh: float,
) -> dict[str, Any] | None:
    """Generate a recommendation when overnight usage is significant."""

    percentage = float(
        metrics["overnight_percentage"]
    )

    if percentage <= OVERNIGHT_USAGE_THRESHOLD:
        return None

    savings = _estimate_savings(
        monthly_kwh,
        OVERNIGHT_SAVINGS_RATE,
    )

    return _make_recommendation(
        title="Review overnight load scheduling",
        category="Overnight",
        description=(
            f"Approximately {percentage:.0%} of the analyzed "
            "energy consumption occurs between midnight and 7 AM. "
            "If flexible equipment can be scheduled during this "
            "window, compare the resulting profile against your "
            "available electricity pricing options."
        ),
        estimated_savings=savings,
        priority="medium",
        confidence=min(
            0.90,
            0.60 + percentage,
        ),
        tags=[
            "overnight",
            "scheduling",
            "load shifting",
        ],
        action=(
            "Identify overnight loads that can be shifted or automated."
        ),
    )


def _heat_pump_recommendation(
    household: Mapping[str, Any],
    monthly_kwh: float,
    average_kwh: float,
) -> dict[str, Any] | None:
    """
    Generate a heating-related recommendation based on household data.

    This does not claim that a heat pump is universally beneficial. It
    identifies an opportunity for further evaluation.
    """

    heating_type = _normalized_text(
        household.get(
            "heating_type"
        )
    )

    if not heating_type:
        return None

    if "heat pump" in heating_type:
        savings = _estimate_savings(
            monthly_kwh,
            HEAT_PUMP_EFFICIENCY_OPPORTUNITY,
        )

        return _make_recommendation(
            title="Optimize heat-pump operation",
            category="HVAC",
            description=(
                "Your household profile indicates heat-pump heating. "
                "Review thermostat schedules, temperature setbacks, "
                "equipment settings, and peak-period operation to "
                "identify potential efficiency improvements."
            ),
            estimated_savings=savings,
            priority="medium",
            confidence=0.75,
            tags=[
                "heat pump",
                "HVAC",
                "efficiency",
            ],
            action=(
                "Review thermostat and HVAC schedules against the "
                "observed load profile."
            ),
        )

    if any(
        keyword in heating_type
        for keyword in (
            "gas",
            "natural gas",
            "oil",
            "propane",
            "electric resistance",
        )
    ):
        savings = _estimate_savings(
            monthly_kwh,
            HEAT_PUMP_ELECTRIFICATION_OPPORTUNITY,
        )

        return _make_recommendation(
            title="Evaluate heat-pump electrification",
            category="HVAC",
            description=(
                "Your household profile indicates a non-heat-pump "
                "heating system. A heat pump could be evaluated as "
                "an electrification option, but the actual economics "
                "depend on equipment performance, building envelope, "
                "climate, fuel prices, and installation costs."
            ),
            estimated_savings=savings,
            priority="medium",
            confidence=0.55,
            tags=[
                "heat pump",
                "electrification",
                "HVAC",
            ],
            action=(
                "Compare equipment, installation, operating costs, "
                "and available incentive programs."
            ),
        )

    return None


def _efficiency_recommendation(
    monthly_kwh: float,
    metrics: Mapping[str, float],
) -> dict[str, Any] | None:
    """
    Identify a general efficiency investigation.

    This is deliberately framed as an investigation rather than claiming that
    insulation definitely produces a particular dollar saving.
    """

    if monthly_kwh <= 0:
        return None

    savings = _estimate_savings(
        monthly_kwh,
        INSULATION_OPPORTUNITY,
    )

    return _make_recommendation(
        title="Investigate building-envelope efficiency",
        category="Efficiency",
        description=(
            "Building-envelope improvements such as air sealing, "
            "attic insulation, wall insulation, or basement insulation "
            "can reduce heating and cooling demand. The actual opportunity "
            "depends on the building envelope and equipment."
        ),
        estimated_savings=savings,
        priority="low",
        confidence=0.40,
        tags=[
            "efficiency",
            "insulation",
            "building envelope",
        ],
        action=(
            "Review insulation and air-sealing condition before "
            "selecting an upgrade."
        ),
    )


def _smart_thermostat_recommendation(
    monthly_kwh: float,
    metrics: Mapping[str, float],
) -> dict[str, Any] | None:
    """
    Suggest thermostat automation only when there is meaningful HVAC-related
    potential.

    Without appliance-level or HVAC-specific data, confidence is intentionally
    low.
    """

    if monthly_kwh <= 0:
        return None

    savings = _estimate_savings(
        monthly_kwh,
        SMART_THERMOSTAT_OPPORTUNITY,
    )

    return _make_recommendation(
        title="Evaluate thermostat automation",
        category="Smart Home",
        description=(
            "Automated temperature schedules can help reduce unnecessary "
            "heating or cooling during unoccupied periods and coordinate "
            "HVAC demand with the household's energy-use pattern."
        ),
        estimated_savings=savings,
        priority="low",
        confidence=0.35,
        tags=[
            "smart home",
            "thermostat",
            "HVAC",
        ],
        action=(
            "Check whether current thermostat schedules already provide "
            "automated temperature setbacks."
        ),
    )


# ---------------------------------------------------------------------------
# Main recommendation engine
# ---------------------------------------------------------------------------

def analyze_usage(
    readings: Iterable[Any] | None,
    household: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Analyze consumption and generate evidence-based recommendations.

    Parameters
    ----------
    readings:
        Historical energy readings containing timestamp and energy_kwh.

    household:
        Optional household configuration. Example:

            {
                "heating_type": "Natural Gas",
                "home_type": "Detached",
                "occupancy": 3
            }

    Returns
    -------
    list[dict]
        Stable recommendation objects suitable for the Flask API.
    """

    df = prepare_dataframe(
        readings
    )

    if df.empty:
        return []

    metrics = calculate_usage_metrics(
        df
    )

    monthly_kwh = _estimate_monthly_usage(
        df
    )

    household_data = normalize_household(
        household
    )

    recommendations: list[
        dict[str, Any]
    ] = []

    # ---------------------------------------------------------------
    # 1. Pricing-plan opportunity
    # ---------------------------------------------------------------

    rate_plan = _rate_plan_recommendation(
        readings
    )

    if rate_plan:
        recommendations.append(
            rate_plan
        )

    # ---------------------------------------------------------------
    # 2. Evening load shifting
    # ---------------------------------------------------------------

    evening = _evening_load_recommendation(
        metrics,
        monthly_kwh,
    )

    if evening:
        recommendations.append(
            evening
        )

    # ---------------------------------------------------------------
    # 3. Overnight usage
    # ---------------------------------------------------------------

    overnight = _overnight_recommendation(
        metrics,
        monthly_kwh,
    )

    if overnight:
        recommendations.append(
            overnight
        )

    # ---------------------------------------------------------------
    # 4. Heating / HVAC
    # ---------------------------------------------------------------

    heating = _heat_pump_recommendation(
        household_data,
        monthly_kwh,
        metrics["average_kwh"],
    )

    if heating:
        recommendations.append(
            heating
        )

    # ---------------------------------------------------------------
    # 5. Building efficiency
    # ---------------------------------------------------------------

    efficiency = _efficiency_recommendation(
        monthly_kwh,
        metrics,
    )

    if efficiency:
        recommendations.append(
            efficiency
        )

    # ---------------------------------------------------------------
    # 6. Smart thermostat
    # ---------------------------------------------------------------

    thermostat = _smart_thermostat_recommendation(
        monthly_kwh,
        metrics,
    )

    if thermostat:
        recommendations.append(
            thermostat
        )

    # ---------------------------------------------------------------
    # Sort recommendations.
    #
    # Priority is the primary ordering signal. Estimated savings is the
    # secondary signal. The original index provides deterministic ordering
    # when both values are equal.
    # ---------------------------------------------------------------

    recommendations = [
        {
            **recommendation,
            "_index": index,
        }
        for index, recommendation in enumerate(
            recommendations
        )
    ]

    recommendations.sort(
        key=lambda recommendation: (
            -PRIORITY_SCORES.get(
                recommendation["priority"],
                0,
            ),
            -_safe_float(
                recommendation.get(
                    "estimated_savings"
                )
            ),
            recommendation["_index"],
        )
    )

    for recommendation in recommendations:
        recommendation.pop(
            "_index",
            None,
        )

    return recommendations


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def summarize_recommendations(
    recommendations: Iterable[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """
    Produce aggregate recommendation statistics.

    This keeps summary calculations out of the React frontend.
    """

    if recommendations is None:
        return {
            "count": 0,
            "monthly_savings_opportunity": 0.0,
            "high_priority_count": 0,
            "categories": [],
        }

    items = list(
        recommendations
    )

    savings = sum(
        _safe_float(
            item.get(
                "estimated_savings"
            )
        )
        for item in items
    )

    high_priority_count = sum(
        1
        for item in items
        if str(
            item.get(
                "priority",
                ""
            )
        ).lower()
        in {
            "critical",
            "high",
        }
    )

    categories = list(
        dict.fromkeys(
            str(
                item.get(
                    "category",
                    ""
                )
            ).strip()
            for item in items
            if str(
                item.get(
                    "category",
                    ""
                )
            ).strip()
        )
    )

    return {
        "count": len(items),
        "monthly_savings_opportunity": round(
            savings,
            2,
        ),
        "high_priority_count": high_priority_count,
        "categories": categories,
    }


__all__ = [
    "analyze_usage",
    "prepare_dataframe",
    "calculate_usage_metrics",
    "normalize_household",
    "summarize_recommendations",
]