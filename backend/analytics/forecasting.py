"""
EnergyPilot forecasting service.

Provides short-term electricity consumption forecasting using:

- Calendar features
- Lag features
- Rolling averages
- Random Forest regression
- Deterministic historical fallback

Forecast units:
    predicted_kwh = estimated energy consumed during the forecast hour.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_PERIODS = 168
MIN_PERIODS = 1
MAX_PERIODS = 24 * 90

# Minimum number of supervised training rows required for ML.
MIN_TRAINING_ROWS = 48

# Forecasting operates on hourly data.
FREQUENCY = "h"

# Historical lag features.
LAG_HOURS = (1, 2, 24, 48, 168)

# Rolling windows.
ROLLING_WINDOWS = (3, 6, 24, 168)

# Random Forest configuration.
RANDOM_STATE = 42
N_ESTIMATORS = 200
MAX_DEPTH = 14
MIN_SAMPLES_LEAF = 2

# Conservative fallback if absolutely no historical data exists.
DEFAULT_BASELINE_KWH = 0.8


# ============================================================================
# Feature definitions
# ============================================================================

BASE_FEATURE_COLUMNS = [
    "hour",
    "day_of_week",
    "day_of_year",
    "week_of_year",
    "month",
    "is_weekend",
    "is_business_hour",
    "sin_hour",
    "cos_hour",
    "sin_week",
    "cos_week",
    "sin_year",
    "cos_year",
]

LAG_FEATURE_COLUMNS = [
    f"lag_{hours}h"
    for hours in LAG_HOURS
]

ROLLING_FEATURE_COLUMNS = [
    f"rolling_mean_{hours}h"
    for hours in ROLLING_WINDOWS
]

FEATURE_COLUMNS = (
    BASE_FEATURE_COLUMNS
    + LAG_FEATURE_COLUMNS
    + ROLLING_FEATURE_COLUMNS
)


# ============================================================================
# Result metadata
# ============================================================================

@dataclass(frozen=True, slots=True)
class ForecastResult:
    """Internal metadata for a forecasting operation."""

    predictions: list[dict[str, Any]]
    method: str
    training_rows: int
    horizon: int


# ============================================================================
# Validation
# ============================================================================

def _validate_periods(periods: int) -> int:
    """Validate the requested forecast horizon."""

    if isinstance(periods, bool):
        raise ValueError("Forecast periods must be an integer.")

    try:
        periods = int(periods)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Forecast periods must be an integer."
        ) from exc

    if periods < MIN_PERIODS:
        raise ValueError(
            f"Forecast periods must be at least {MIN_PERIODS}."
        )

    if periods > MAX_PERIODS:
        raise ValueError(
            f"Forecast periods cannot exceed {MAX_PERIODS}."
        )

    return periods


# ============================================================================
# Data extraction
# ============================================================================

def _empty_dataframe() -> pd.DataFrame:
    """Return a consistently shaped empty DataFrame."""

    return pd.DataFrame(
        {
            "timestamp": pd.Series(
                dtype="datetime64[ns, UTC]"
            ),
            "energy_kwh": pd.Series(
                dtype="float64"
            ),
        }
    )


def _extract_reading_value(
    reading: Any,
    field: str,
) -> Any:
    """
    Extract a field from either a mapping or an object.

    Supports:

    - dict
    - database records
    - dataclasses
    - simple Python objects
    """

    if isinstance(reading, Mapping):
        return reading.get(field)

    return getattr(reading, field, None)


# ============================================================================
# Data preparation
# ============================================================================

def prepare_dataframe(
    readings: Iterable[Any] | None,
) -> pd.DataFrame:
    """
    Normalize raw readings into an hourly time series.

    Steps:

    1. Extract timestamp and energy.
    2. Parse timestamps as UTC.
    3. Convert energy to numeric.
    4. Remove invalid values.
    5. Remove negative consumption.
    6. Aggregate duplicate timestamps.
    7. Resample to hourly frequency.
    8. Interpolate short gaps.
    9. Fill remaining gaps using the median.
    """

    if readings is None:
        return _empty_dataframe()

    rows: list[dict[str, Any]] = []

    for reading in readings:
        rows.append(
            {
                "timestamp": _extract_reading_value(
                    reading,
                    "timestamp",
                ),
                "energy_kwh": _extract_reading_value(
                    reading,
                    "energy_kwh",
                ),
            }
        )

    if not rows:
        return _empty_dataframe()

    df = pd.DataFrame(rows)

    if not {
        "timestamp",
        "energy_kwh",
    }.issubset(df.columns):
        return _empty_dataframe()

    # Normalize timestamps.
    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce",
        utc=True,
    )

    # Normalize energy values.
    df["energy_kwh"] = pd.to_numeric(
        df["energy_kwh"],
        errors="coerce",
    )

    # Remove invalid timestamps / values.
    df = df.dropna(
        subset=[
            "timestamp",
            "energy_kwh",
        ]
    )

    # Energy consumption cannot be negative.
    df = df[df["energy_kwh"] >= 0]

    # Remove infinity values.
    finite_mask = np.isfinite(
        df["energy_kwh"].to_numpy(dtype=float)
    )

    df = df.loc[finite_mask]

    if df.empty:
        return _empty_dataframe()

    # Aggregate duplicate timestamps rather than arbitrarily dropping them.
    df = (
        df.groupby(
            "timestamp",
            as_index=False,
            sort=True,
        )["energy_kwh"]
        .sum()
    )

    df = df.set_index("timestamp")

    # Convert to regular hourly observations.
    df = df.resample(FREQUENCY).mean()

    if df.empty:
        return _empty_dataframe()

    # Interpolate short gaps.
    df["energy_kwh"] = df["energy_kwh"].interpolate(
        method="time",
        limit=6,
        limit_direction="both",
    )

    # Fill long gaps with historical median.
    median_energy = df["energy_kwh"].median()

    if pd.isna(median_energy):
        median_energy = DEFAULT_BASELINE_KWH

    df["energy_kwh"] = (
        df["energy_kwh"]
        .fillna(float(median_energy))
        .clip(lower=0)
    )

    return df.reset_index()


# ============================================================================
# Calendar features
# ============================================================================

def add_calendar_features(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Add calendar and cyclical time features."""

    result = df.copy()

    timestamp = result["timestamp"]

    result["hour"] = timestamp.dt.hour
    result["day_of_week"] = timestamp.dt.dayofweek
    result["day_of_year"] = timestamp.dt.dayofyear
    result["week_of_year"] = (
        timestamp.dt.isocalendar().week.astype(int)
    )
    result["month"] = timestamp.dt.month

    result["is_weekend"] = (
        result["day_of_week"] >= 5
    ).astype(int)

    result["is_business_hour"] = (
        result["hour"].between(8, 18)
        & (result["is_weekend"] == 0)
    ).astype(int)

    # Daily cycle.
    result["sin_hour"] = np.sin(
        2 * np.pi * result["hour"] / 24
    )

    result["cos_hour"] = np.cos(
        2 * np.pi * result["hour"] / 24
    )

    # Weekly cycle.
    result["sin_week"] = np.sin(
        2 * np.pi * result["day_of_week"] / 7
    )

    result["cos_week"] = np.cos(
        2 * np.pi * result["day_of_week"] / 7
    )

    # Annual cycle.
    result["sin_year"] = np.sin(
        2 * np.pi * result["day_of_year"] / 365.25
    )

    result["cos_year"] = np.cos(
        2 * np.pi * result["day_of_year"] / 365.25
    )

    return result


# ============================================================================
# Lag and rolling features
# ============================================================================

def add_lag_features(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Add historical consumption features."""

    result = df.copy()

    for hours in LAG_HOURS:
        result[f"lag_{hours}h"] = (
            result["energy_kwh"].shift(hours)
        )

    for hours in ROLLING_WINDOWS:
        result[f"rolling_mean_{hours}h"] = (
            result["energy_kwh"]
            .shift(1)
            .rolling(
                window=hours,
                min_periods=max(1, hours // 2),
            )
            .mean()
        )

    return result


def add_features(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Build the complete forecasting feature set."""

    result = add_calendar_features(df)

    if "energy_kwh" in result.columns:
        result = add_lag_features(result)

    return result


# ============================================================================
# Model
# ============================================================================

def build_model() -> RandomForestRegressor:
    """Construct the Random Forest forecasting model."""

    return RandomForestRegressor(
        n_estimators=N_ESTIMATORS,
        random_state=RANDOM_STATE,
        max_depth=MAX_DEPTH,
        min_samples_leaf=MIN_SAMPLES_LEAF,
        n_jobs=-1,
    )


# ============================================================================
# Training
# ============================================================================

def _training_frame(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Build the supervised-learning training dataset."""

    featured = add_features(df)

    required_columns = [
        *FEATURE_COLUMNS,
        "energy_kwh",
    ]

    missing = [
        column
        for column in required_columns
        if column not in featured.columns
    ]

    if missing:
        raise ValueError(
            "Missing forecasting features: "
            + ", ".join(missing)
        )

    return featured[
        required_columns
    ].dropna()


# ============================================================================
# Fallback forecasting
# ============================================================================

def _seasonal_baseline_prediction(
    df: pd.DataFrame,
    timestamp: pd.Timestamp,
) -> float:
    """
    Estimate consumption using historical patterns.

    Preference:

    1. Same hour + same weekday
    2. Same hour
    3. Recent 24 hours
    4. Global baseline
    """

    if df.empty:
        return DEFAULT_BASELINE_KWH

    same_hour_weekday = df[
        (df["timestamp"].dt.hour == timestamp.hour)
        & (
            df["timestamp"].dt.dayofweek
            == timestamp.dayofweek
        )
    ]

    if not same_hour_weekday.empty:
        return float(
            same_hour_weekday[
                "energy_kwh"
            ].tail(8).mean()
        )

    same_hour = df[
        df["timestamp"].dt.hour
        == timestamp.hour
    ]

    if not same_hour.empty:
        return float(
            same_hour[
                "energy_kwh"
            ].tail(14).mean()
        )

    recent = df["energy_kwh"].tail(24)

    if not recent.empty:
        return float(recent.mean())

    return DEFAULT_BASELINE_KWH


def _serialize_predictions(
    timestamps: Iterable[pd.Timestamp],
    predictions: Iterable[float],
) -> list[dict[str, Any]]:
    """Convert predictions into API-safe dictionaries."""

    result: list[dict[str, Any]] = []

    for timestamp, prediction in zip(
        timestamps,
        predictions,
    ):
        value = float(prediction)

        if not np.isfinite(value):
            value = 0.0

        result.append(
            {
                "timestamp": timestamp.isoformat(),
                "predicted_kwh": round(
                    max(0.0, value),
                    3,
                ),
            }
        )

    return result


def fallback_forecast(
    df: pd.DataFrame,
    periods: int,
) -> list[dict[str, Any]]:
    """Generate a deterministic non-ML forecast."""

    periods = _validate_periods(periods)

    if df.empty:
        last_timestamp = pd.Timestamp.now(
            tz="UTC"
        )
    else:
        last_timestamp = df["timestamp"].max()

    future_times = pd.date_range(
        start=last_timestamp
        + pd.Timedelta(hours=1),
        periods=periods,
        freq=FREQUENCY,
    )

    predictions = [
        _seasonal_baseline_prediction(
            df,
            timestamp,
        )
        for timestamp in future_times
    ]

    return _serialize_predictions(
        future_times,
        predictions,
    )


# ============================================================================
# Recursive prediction
# ============================================================================

def _predict_recursive(
    model: RandomForestRegressor,
    history: pd.DataFrame,
    periods: int,
) -> np.ndarray:
    """
    Generate future predictions recursively.

    Each prediction becomes part of the history used for subsequent
    predictions.
    """

    working = history[
        [
            "timestamp",
            "energy_kwh",
        ]
    ].copy()

    future_times = pd.date_range(
        start=working["timestamp"].max()
        + pd.Timedelta(hours=1),
        periods=periods,
        freq=FREQUENCY,
    )

    predictions: list[float] = []

    for timestamp in future_times:
        candidate = pd.concat(
            [
                working,
                pd.DataFrame(
                    {
                        "timestamp": [timestamp],
                        "energy_kwh": [np.nan],
                    }
                ),
            ],
            ignore_index=True,
        )

        featured = add_features(candidate)

        current_features = featured.iloc[[-1]][
            FEATURE_COLUMNS
        ]

        if current_features.isna().any().any():
            prediction = _seasonal_baseline_prediction(
                working,
                timestamp,
            )
        else:
            prediction = float(
                model.predict(
                    current_features
                )[0]
            )

        prediction = max(
            0.0,
            prediction,
        )

        predictions.append(prediction)

        # Feed prediction back into history.
        working = pd.concat(
            [
                working,
                pd.DataFrame(
                    {
                        "timestamp": [timestamp],
                        "energy_kwh": [prediction],
                    }
                ),
            ],
            ignore_index=True,
        )

    return np.asarray(
        predictions,
        dtype=float,
    )


# ============================================================================
# Public forecasting API
# ============================================================================

def forecast_usage(
    readings: Iterable[Any] | None,
    periods: int = DEFAULT_PERIODS,
) -> list[dict[str, Any]]:
    """
    Forecast future electricity consumption.

    Returns dictionaries containing:

        timestamp
        predicted_kwh
    """

    periods = _validate_periods(periods)

    df = prepare_dataframe(readings)

    if df.empty:
        return fallback_forecast(
            df,
            periods,
        )

    if len(df) < MIN_TRAINING_ROWS:
        return fallback_forecast(
            df,
            periods,
        )

    training = _training_frame(df)

    if len(training) < MIN_TRAINING_ROWS:
        return fallback_forecast(
            df,
            periods,
        )

    X = training[FEATURE_COLUMNS]
    y = training["energy_kwh"]

    if X.empty or y.empty:
        return fallback_forecast(
            df,
            periods,
        )

    if not np.isfinite(
        X.to_numpy(dtype=float)
    ).all():
        return fallback_forecast(
            df,
            periods,
        )

    if not np.isfinite(
        y.to_numpy(dtype=float)
    ).all():
        return fallback_forecast(
            df,
            periods,
        )

    model = build_model()

    model.fit(
        X,
        y,
    )

    predictions = _predict_recursive(
        model=model,
        history=df,
        periods=periods,
    )

    future_times = pd.date_range(
        start=df["timestamp"].max()
        + pd.Timedelta(hours=1),
        periods=periods,
        freq=FREQUENCY,
    )

    return _serialize_predictions(
        future_times,
        predictions,
    )


# ============================================================================
# Diagnostics
# ============================================================================

def get_forecast_model_info(
    readings: Iterable[Any] | None,
) -> dict[str, Any]:
    """Return forecast readiness diagnostics."""

    df = prepare_dataframe(readings)

    if df.empty:
        return {
            "method": "fallback",
            "training_rows": 0,
            "history_hours": 0,
            "ready_for_ml": False,
            "reason": "No valid historical readings.",
        }

    training = _training_frame(df)

    ready = len(training) >= MIN_TRAINING_ROWS

    return {
        "method": (
            "random_forest"
            if ready
            else "fallback"
        ),
        "training_rows": int(
            len(training)
        ),
        "history_hours": int(
            len(df)
        ),
        "ready_for_ml": ready,
        "reason": (
            "Sufficient historical data."
            if ready
            else "Insufficient historical data for ML features."
        ),
    }


__all__ = [
    "forecast_usage",
    "fallback_forecast",
    "prepare_dataframe",
    "add_calendar_features",
    "add_lag_features",
    "add_features",
    "build_model",
    "get_forecast_model_info",
]