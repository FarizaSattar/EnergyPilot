"""
EnergyPilot context builder.

This module converts raw application data into a compact, deterministic
context object for downstream recommendation and LLM layers.

Architecture:

    PostgreSQL / simulator / weather / pricing / forecasting
                            |
                            v
                       context.py
                            |
                            v
                  structured factual context
                            |
                 +----------+----------+
                 |                     |
                 v                     v
          recommendations.py        llm.py
          
Design principles
-----------------
1. This module performs deterministic data preparation only.
2. It does not generate recommendations.
3. It does not ask an LLM to calculate metrics.
4. It does not invent missing values.
5. Energy and power units remain explicit:
       kWh = energy consumed over an interval
       kW  = demand/power
6. Raw datasets are summarized rather than passed wholesale to an LLM.
7. User/provider supplied strings are treated as data, not instructions.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import pandas as pd


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_MAX_FORECAST_POINTS = 168
DEFAULT_MAX_DAILY_POINTS = 31
DEFAULT_MAX_CONTEXT_BYTES = 50_000

OVERNIGHT_START_HOUR = 23
OVERNIGHT_END_HOUR = 7


# =============================================================================
# Exceptions
# =============================================================================

class EnergyContextError(Exception):
    """Base exception for context-building failures."""


class EnergyContextValidationError(EnergyContextError):
    """Raised when required input data is invalid."""


# =============================================================================
# Generic helpers
# =============================================================================

def _is_finite(value: Any) -> bool:
    """Return True for finite numeric values."""
    if value is None or isinstance(value, bool):
        return False

    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _safe_float(
    value: Any,
) -> float | None:
    """Convert a value to a finite float, otherwise return None."""
    if not _is_finite(value):
        return None

    return float(value)


def _round_if_numeric(
    value: Any,
    digits: int = 3,
) -> float | None:
    """Round a finite numeric value without inventing missing data."""
    numeric = _safe_float(value)

    if numeric is None:
        return None

    return round(numeric, digits)


def _clean_mapping(
    value: Any,
) -> dict[str, Any]:
    """
    Convert an optional mapping into a plain dictionary.

    A context object should contain ordinary JSON-compatible structures,
    rather than custom mapping subclasses.
    """
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise EnergyContextValidationError(
            "Expected a mapping/dictionary."
        )

    return dict(value)


def _json_safe(
    value: Any,
) -> Any:
    """
    Recursively convert common Python/Pandas values into JSON-safe values.

    This is intentionally conservative. Unknown objects are converted to
    strings only at the final boundary rather than throughout the pipeline.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [
            _json_safe(item)
            for item in value
        ]

    return value


# =============================================================================
# Reading preparation
# =============================================================================

def _prepare_readings(
    readings: Any,
) -> pd.DataFrame:
    """
    Validate and normalize meter readings.

    Invalid rows are removed rather than silently converted to zero.

    This is important because:
        None -> 0
        NaN  -> 0
        "abc" -> 0

    would materially distort energy statistics.
    """
    if readings is None:
        return pd.DataFrame()

    if isinstance(readings, pd.DataFrame):
        dataframe = readings.copy()

    else:
        try:
            dataframe = pd.DataFrame(
                list(readings)
            )
        except (TypeError, ValueError) as exc:
            raise EnergyContextValidationError(
                "readings must be a DataFrame or iterable of records."
            ) from exc

    if dataframe.empty:
        return dataframe

    if "timestamp" not in dataframe.columns:
        # Support the PostgreSQL naming used by the current backend.
        if "ts" in dataframe.columns:
            dataframe = dataframe.rename(
                columns={"ts": "timestamp"}
            )
        else:
            raise EnergyContextValidationError(
                "Readings require a 'timestamp' field."
            )

    if "energy_kwh" not in dataframe.columns:
        raise EnergyContextValidationError(
            "Readings require an 'energy_kwh' field."
        )

    dataframe["timestamp"] = pd.to_datetime(
        dataframe["timestamp"],
        errors="coerce",
        utc=True,
    )

    dataframe["energy_kwh"] = pd.to_numeric(
        dataframe["energy_kwh"],
        errors="coerce",
    )

    # Demand is optional because some historical datasets may only contain
    # energy readings. When available, however, it should be preserved.
    if "demand_kw" in dataframe.columns:
        dataframe["demand_kw"] = pd.to_numeric(
            dataframe["demand_kw"],
            errors="coerce",
        )

    # Additional telemetry is optional.
    for column in (
        "temperature_c",
        "occupancy",
        "hvac_kw",
        "lighting_kw",
    ):
        if column in dataframe.columns:
            dataframe[column] = pd.to_numeric(
                dataframe[column],
                errors="coerce",
            )

    # A reading without a valid timestamp or energy value cannot participate
    # in the energy analysis.
    dataframe = dataframe.dropna(
        subset=[
            "timestamp",
            "energy_kwh",
        ]
    )

    # Negative energy consumption is invalid for this application's current
    # meter-reading contract.
    dataframe = dataframe[
        dataframe["energy_kwh"] >= 0
    ]

    if "demand_kw" in dataframe.columns:
        dataframe.loc[
            dataframe["demand_kw"] < 0,
            "demand_kw",
        ] = float("nan")

    dataframe = (
        dataframe
        .sort_values("timestamp")
        .drop_duplicates(
            subset=["timestamp"],
            keep="last",
        )
        .reset_index(drop=True)
    )

    return dataframe


# =============================================================================
# Energy metrics
# =============================================================================

def _calculate_energy_metrics(
    dataframe: pd.DataFrame,
) -> dict[str, Any]:
    """Calculate deterministic energy and demand statistics."""
    if dataframe.empty:
        return {}

    energy = dataframe["energy_kwh"]

    total_kwh = float(
        energy.sum()
    )

    average_kwh = float(
        energy.mean()
    )

    peak_energy_kwh = float(
        energy.max()
    )

    peak_energy_index = energy.idxmax()

    peak_energy_row = dataframe.loc[
        peak_energy_index
    ]

    metrics: dict[str, Any] = {
        "record_count": int(
            len(dataframe)
        ),

        "total_kwh": round(
            total_kwh,
            2,
        ),

        "average_reading_kwh": round(
            average_kwh,
            3,
        ),

        "peak_reading_kwh": round(
            peak_energy_kwh,
            3,
        ),

        "peak_timestamp": (
            peak_energy_row["timestamp"].isoformat()
        ),

        "first_timestamp": (
            dataframe["timestamp"]
            .min()
            .isoformat()
        ),

        "last_timestamp": (
            dataframe["timestamp"]
            .max()
            .isoformat()
        ),
    }

    # -------------------------------------------------------------------------
    # Demand metrics
    # -------------------------------------------------------------------------

    if "demand_kw" in dataframe.columns:
        valid_demand = dataframe[
            dataframe["demand_kw"].notna()
            & (dataframe["demand_kw"] >= 0)
        ]

        if not valid_demand.empty:
            peak_demand_index = (
                valid_demand["demand_kw"].idxmax()
            )

            peak_demand_row = dataframe.loc[
                peak_demand_index
            ]

            metrics.update(
                {
                    "average_demand_kw": round(
                        float(
                            valid_demand[
                                "demand_kw"
                            ].mean()
                        ),
                        3,
                    ),

                    "peak_demand_kw": round(
                        float(
                            valid_demand[
                                "demand_kw"
                            ].max()
                        ),
                        3,
                    ),

                    "peak_demand_timestamp": (
                        peak_demand_row[
                            "timestamp"
                        ].isoformat()
                    ),
                }
            )

    # -------------------------------------------------------------------------
    # Overnight usage
    # -------------------------------------------------------------------------

    hours = dataframe[
        "timestamp"
    ].dt.hour

    overnight_mask = (
        (hours >= OVERNIGHT_START_HOUR)
        | (hours < OVERNIGHT_END_HOUR)
    )

    overnight = dataframe[
        overnight_mask
    ]

    overnight_kwh = float(
        overnight["energy_kwh"].sum()
    )

    overnight_share = (
        overnight_kwh / total_kwh
        if total_kwh > 0
        else 0.0
    )

    metrics.update(
        {
            "overnight_kwh": round(
                overnight_kwh,
                2,
            ),

            "overnight_share": round(
                overnight_share,
                3,
            ),

            "overnight_record_count": int(
                len(overnight)
            ),
        }
    )

    # -------------------------------------------------------------------------
    # Daily statistics
    # -------------------------------------------------------------------------

    daily = (
        dataframe
        .set_index("timestamp")
        ["energy_kwh"]
        .resample("D")
        .sum()
    )

    if not daily.empty:
        metrics.update(
            {
                "days_observed": int(
                    daily.shape[0]
                ),

                "average_daily_kwh": round(
                    float(
                        daily.mean()
                    ),
                    2,
                ),

                "peak_daily_kwh": round(
                    float(
                        daily.max()
                    ),
                    2,
                ),
            }
        )

    return metrics


# =============================================================================
# Load-profile metrics
# =============================================================================

def _calculate_load_profile(
    dataframe: pd.DataFrame,
) -> dict[str, Any]:
    """
    Build a compact hourly profile.

    The result is intentionally small enough to pass downstream to an LLM
    without including every raw meter reading.
    """
    if dataframe.empty:
        return {}

    working = dataframe.copy()

    working["hour"] = (
        working["timestamp"].dt.hour
    )

    grouped = (
        working
        .groupby("hour")["energy_kwh"]
        .mean()
    )

    hourly_profile = [
        {
            "hour": int(hour),
            "average_kwh": round(
                float(value),
                3,
            ),
        }
        for hour, value in grouped.items()
    ]

    result: dict[str, Any] = {
        "hourly_profile": hourly_profile,
    }

    # Weekday/weekend comparison provides useful context without exposing
    # the complete raw dataset.
    working["is_weekend"] = (
        working["timestamp"].dt.dayofweek >= 5
    )

    weekend = working[
        working["is_weekend"]
    ]["energy_kwh"]

    weekday = working[
        ~working["is_weekend"]
    ]["energy_kwh"]

    if not weekday.empty:
        result["weekday_average_kwh"] = round(
            float(weekday.mean()),
            3,
        )

    if not weekend.empty:
        result["weekend_average_kwh"] = round(
            float(weekend.mean()),
            3,
        )

    return result


# =============================================================================
# Environmental / telemetry metrics
# =============================================================================

def _calculate_environment_metrics(
    dataframe: pd.DataFrame,
) -> dict[str, Any]:
    """Summarize optional temperature, occupancy, and end-use telemetry."""
    if dataframe.empty:
        return {}

    result: dict[str, Any] = {}

    if "temperature_c" in dataframe.columns:
        temperature = dataframe[
            "temperature_c"
        ].dropna()

        if not temperature.empty:
            result.update(
                {
                    "average_temperature_c": round(
                        float(temperature.mean()),
                        2,
                    ),

                    "minimum_temperature_c": round(
                        float(temperature.min()),
                        2,
                    ),

                    "maximum_temperature_c": round(
                        float(temperature.max()),
                        2,
                    ),
                }
            )

    if "occupancy" in dataframe.columns:
        occupancy = dataframe[
            "occupancy"
        ].dropna()

        if not occupancy.empty:
            result.update(
                {
                    "average_occupancy": round(
                        float(occupancy.mean()),
                        2,
                    ),

                    "maximum_occupancy": round(
                        float(occupancy.max()),
                        2,
                    ),
                }
            )

    if "hvac_kw" in dataframe.columns:
        hvac = dataframe[
            "hvac_kw"
        ].dropna()

        hvac = hvac[
            hvac >= 0
        ]

        if not hvac.empty:
            result["average_hvac_kw"] = round(
                float(hvac.mean()),
                3,
            )

            result["peak_hvac_kw"] = round(
                float(hvac.max()),
                3,
            )

    if "lighting_kw" in dataframe.columns:
        lighting = dataframe[
            "lighting_kw"
        ].dropna()

        lighting = lighting[
            lighting >= 0
        ]

        if not lighting.empty:
            result["average_lighting_kw"] = round(
                float(lighting.mean()),
                3,
            )

            result["peak_lighting_kw"] = round(
                float(lighting.max()),
                3,
            )

    return result


# =============================================================================
# Daily usage
# =============================================================================

def _build_daily_usage(
    dataframe: pd.DataFrame,
    max_points: int,
) -> list[dict[str, Any]]:
    """Return a bounded chronological daily-energy series."""
    if dataframe.empty:
        return []

    daily = (
        dataframe
        .set_index("timestamp")
        ["energy_kwh"]
        .resample("D")
        .sum()
        .tail(max_points)
    )

    return [
        {
            "date": timestamp.date().isoformat(),
            "kwh": round(
                float(value),
                3,
            ),
        }
        for timestamp, value in daily.items()
    ]


# =============================================================================
# Forecast normalization
# =============================================================================

def _normalize_forecast(
    forecast: Any,
    max_points: int,
) -> Any:
    """
    Keep only useful forecast information.

    Forecasts can become surprisingly large, so the context layer should not
    blindly forward an entire provider/model response to an LLM.
    """
    if forecast is None:
        return {}

    if not isinstance(forecast, Mapping):
        return {}

    result = dict(forecast)

    for key in (
        "hourly",
        "forecast",
        "predictions",
        "points",
    ):
        value = result.get(key)

        if isinstance(value, list):
            result[key] = value[
                :max_points
            ]

    return _json_safe(result)


# =============================================================================
# Context size protection
# =============================================================================

def _limit_context_size(
    context: dict[str, Any],
    max_bytes: int,
) -> dict[str, Any]:
    """
    Prevent accidental oversized LLM prompts.

    This is a safety and reliability boundary rather than an optimization:
    uploaded datasets and third-party strings should never be able to create
    an unexpectedly huge model request.
    """
    if max_bytes <= 0:
        raise ValueError(
            "max_bytes must be positive."
        )

    safe_context = _json_safe(
        context
    )

    # Avoid importing a JSON serializer merely for normal application logic.
    # repr() is sufficient for an approximate byte-size guard here.
    estimated_bytes = len(
        repr(safe_context).encode(
            "utf-8"
        )
    )

    if estimated_bytes <= max_bytes:
        return safe_context

    # The context is already summarized, so an oversized result indicates
    # unusually large provider metadata or household strings.
    #
    # Rather than silently truncating arbitrary data, fail explicitly. This
    # makes the problem observable and prevents corrupted JSON-like context.
    raise EnergyContextError(
        "Energy context exceeds the configured size limit."
    )


# =============================================================================
# Public API
# =============================================================================

def build_energy_context(
    readings: Any,
    household: Mapping[str, Any] | None = None,
    weather: Mapping[str, Any] | None = None,
    pricing: Mapping[str, Any] | None = None,
    forecast: Mapping[str, Any] | None = None,
    *,
    max_forecast_points: int = DEFAULT_MAX_FORECAST_POINTS,
    max_daily_points: int = DEFAULT_MAX_DAILY_POINTS,
    max_context_bytes: int = DEFAULT_MAX_CONTEXT_BYTES,
) -> dict[str, Any]:
    """
    Build a deterministic, compact EnergyPilot context object.

    Parameters
    ----------
    readings:
        Iterable of meter-reading dictionaries or a pandas DataFrame.

    household:
        Household/building configuration.

    weather:
        Normalized weather-service output.

    pricing:
        Normalized electricity pricing information.

    forecast:
        Normalized demand forecast.

    max_forecast_points:
        Maximum number of forecast records retained.

    max_daily_points:
        Maximum number of daily usage records retained.

    max_context_bytes:
        Maximum approximate serialized context size.

    Returns
    -------
    dict
        JSON-safe structured context suitable for deterministic analytics
        and/or LLM explanation.

    Notes
    -----
    The returned values describe observed or supplied data. This function does
    not estimate savings or generate recommendations.
    """
    if not 1 <= max_forecast_points <= 10_000:
        raise ValueError(
            "max_forecast_points must be between 1 and 10,000."
        )

    if not 1 <= max_daily_points <= 365:
        raise ValueError(
            "max_daily_points must be between 1 and 365."
        )

    dataframe = _prepare_readings(
        readings
    )

    household_data = _clean_mapping(
        household
    )

    weather_data = _clean_mapping(
        weather
    )

    pricing_data = _clean_mapping(
        pricing
    )

    energy: dict[str, Any] = {}

    if not dataframe.empty:
        energy.update(
            _calculate_energy_metrics(
                dataframe
            )
        )

        energy.update(
            _calculate_load_profile(
                dataframe
            )
        )

        energy.update(
            _calculate_environment_metrics(
                dataframe
            )
        )

        energy["daily_usage"] = (
            _build_daily_usage(
                dataframe,
                max_daily_points,
            )
        )

    context = {
        "household": household_data,

        "energy": energy,

        "weather": weather_data,

        "pricing": pricing_data,

        "forecast": _normalize_forecast(
            forecast,
            max_forecast_points,
        ),

        "meta": {
            "context_version": "1.0",
            "data_available": not dataframe.empty,
            "reading_count": int(
                len(dataframe)
            ),
            "units": {
                "energy": "kWh",
                "power": "kW",
                "temperature": "°C",
            },
        },
    }

    return _limit_context_size(
        context,
        max_context_bytes,
    )


__all__ = [
    "EnergyContextError",
    "EnergyContextValidationError",
    "build_energy_context",
]