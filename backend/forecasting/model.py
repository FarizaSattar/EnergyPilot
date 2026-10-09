"""
EnergyPilot forecasting model.

This module owns the machine-learning portion of the forecasting pipeline:

    PostgreSQL / simulator / CSV
              |
              v
        historical readings
              |
              v
        make_features()
              |
              v
        train_model()
              |
              +----> evaluation metrics
              |
              v
        saved model artifact
              |
              v
        predict()

The module intentionally contains no Flask/API/database code. Keeping the
model layer independent makes it easier to test, retrain, and eventually
replace RandomForestRegressor with another forecasting algorithm.

Forecast target:
    demand_kw

Feature assumptions:
    - telemetry is hourly
    - `ts` is the observation timestamp
    - `demand_kw` is the demand for that interval
    - temperature_c and occupancy are optional input features

IMPORTANT:
    lag_1, lag_24, and lag_168 only have their intended meaning when the
    underlying data is approximately hourly:

        lag_1   -> previous hour
        lag_24  -> same hour yesterday
        lag_168 -> same hour last week
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error


# =============================================================================
# Configuration
# =============================================================================

MODEL_PATH = Path(__file__).resolve().parent / "energy_model.joblib"

TARGET = "demand_kw"

# Keep this list centralized so training and inference cannot accidentally use
# different feature sets.
FEATURES = [
    "hour",
    "day_of_week",
    "is_weekend",
    "temperature_c",
    "occupancy",
    "lag_1",
    "lag_24",
    "lag_168",
    "rolling_mean_24",
]

# These values are deliberately conservative. A forecasting model should fail
# clearly when there isn't enough history rather than silently training on an
# unreliable dataset.
MIN_RAW_SAMPLES = 24 * 8       # At least one week + one day of hourly data.
MIN_TRAIN_SAMPLES = 24 * 5
MIN_TEST_SAMPLES = 24

DEFAULT_RANDOM_STATE = 42
DEFAULT_N_ESTIMATORS = 250
DEFAULT_MAX_DEPTH = 12
DEFAULT_MIN_SAMPLES_LEAF = 2

EXPECTED_FREQUENCY = "h"


# =============================================================================
# Data structures
# =============================================================================

@dataclass(frozen=True)
class ModelMetrics:
    """
    Evaluation metrics returned after training.

    Keeping metrics in a small immutable object makes it harder for callers
    to accidentally mutate the result and gives us a stable serialization
    format for the API layer.
    """

    mae_kw: float
    rmse_kw: float
    samples: int
    train_samples: int
    test_samples: int
    baseline_mae_kw: float | None = None
    baseline_rmse_kw: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly metrics."""
        return asdict(self)


@dataclass(frozen=True)
class ModelArtifact:
    """
    Metadata stored alongside the fitted sklearn model.

    Persisting metadata prevents a future application version from loading a
    model without knowing which features and configuration produced it.
    """

    model_version: str
    target: str
    features: tuple[str, ...]
    frequency: str
    random_state: int
    n_estimators: int
    max_depth: int | None
    min_samples_leaf: int


# =============================================================================
# Validation helpers
# =============================================================================

def _require_dataframe(df: pd.DataFrame) -> None:
    """Validate that the forecasting pipeline received a DataFrame."""
    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"Expected pandas.DataFrame, got {type(df).__name__}."
        )

    if df.empty:
        raise ValueError("Forecasting dataset is empty.")


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    """Raise a useful error when required telemetry columns are missing."""
    missing = [column for column in columns if column not in df.columns]

    if missing:
        raise ValueError(
            "Forecasting dataset is missing required columns: "
            + ", ".join(missing)
        )


def _clean_numeric_column(
    df: pd.DataFrame,
    column: str,
    *,
    default: float | None = None,
) -> pd.Series:
    """
    Convert a telemetry column to numeric values.

    Invalid values become NaN. The caller can then decide whether to impute
    them or remove those rows.
    """
    values = pd.to_numeric(df[column], errors="coerce")

    if default is not None:
        values = values.fillna(default)

    return values


def _validate_target(df: pd.DataFrame) -> None:
    """Validate the physical target variable used by the model."""
    target = pd.to_numeric(df[TARGET], errors="coerce")

    if target.isna().all():
        raise ValueError("demand_kw contains no usable numeric values.")

    if (target.dropna() < 0).any():
        raise ValueError("demand_kw cannot contain negative values.")


def _validate_timestamps(df: pd.DataFrame) -> None:
    """Ensure timestamps are usable and contain no duplicate observations."""
    if df["ts"].isna().any():
        raise ValueError("Forecasting data contains invalid timestamps.")

    if df["ts"].duplicated().any():
        raise ValueError(
            "Forecasting data contains duplicate timestamps. "
            "Deduplicate telemetry before training."
        )


# =============================================================================
# Feature engineering
# =============================================================================

def make_features(
    df: pd.DataFrame,
    *,
    dropna: bool = True,
) -> pd.DataFrame:
    """
    Convert raw hourly telemetry into supervised-learning features.

    Features include:

        hour             -> time-of-day pattern
        day_of_week      -> weekly pattern
        is_weekend       -> weekday/weekend behavior
        temperature_c    -> weather sensitivity
        occupancy        -> building activity
        lag_1            -> previous-hour demand
        lag_24           -> same-hour previous-day demand
        lag_168          -> same-hour previous-week demand
        rolling_mean_24  -> recent 24-hour demand baseline

    The rolling feature is shifted by one period before calculating the
    rolling mean. This is critical: the current target must never be included
    in a feature used to predict itself.

    Parameters
    ----------
    df:
        Raw telemetry DataFrame containing at least `ts` and `demand_kw`.

    dropna:
        If True, remove rows that cannot have complete lag/rolling features.

    Returns
    -------
    pandas.DataFrame
        Feature-engineered dataset.
    """
    _require_dataframe(df)
    _require_columns(df, ["ts", TARGET])
    _validate_target(df)

    data = df.copy()

    # UTC normalization gives the ML pipeline a deterministic time basis.
    # If the application wants local building-hour features, timestamps should
    # first be converted to the building's configured timezone.
    data["ts"] = pd.to_datetime(data["ts"], errors="coerce", utc=True)

    if data["ts"].isna().any():
        raise ValueError("One or more timestamps could not be parsed.")

    data = data.sort_values("ts").reset_index(drop=True)
    _validate_timestamps(data)

    data[TARGET] = pd.to_numeric(data[TARGET], errors="coerce")

    # Optional environmental features.
    #
    # Missing telemetry should not cause the entire forecast pipeline to
    # crash. Median imputation is performed after sorting so it remains
    # deterministic. More sophisticated production pipelines can replace this
    # with model-specific imputation.
    if "temperature_c" not in data.columns:
        data["temperature_c"] = np.nan

    if "occupancy" not in data.columns:
        data["occupancy"] = np.nan

    data["temperature_c"] = _clean_numeric_column(data, "temperature_c")
    data["occupancy"] = _clean_numeric_column(data, "occupancy")

    # Fill optional sensor values with robust defaults.
    #
    # Temperature uses the dataset median rather than 0°C because 0 is a real
    # physical temperature and would introduce a false signal.
    temperature_median = data["temperature_c"].median()

    if pd.isna(temperature_median):
        temperature_median = 15.0

    data["temperature_c"] = data["temperature_c"].fillna(temperature_median)

    # Occupancy is a count, so zero is a reasonable fallback when telemetry
    # is unavailable.
    data["occupancy"] = data["occupancy"].fillna(0).clip(lower=0)

    # Calendar features.
    data["hour"] = data["ts"].dt.hour
    data["day_of_week"] = data["ts"].dt.dayofweek
    data["is_weekend"] = (data["day_of_week"] >= 5).astype(int)

    # Historical demand features.
    #
    # These are intentionally based only on prior observations. Using
    # shift(1) for the rolling window prevents target leakage.
    for lag in (1, 24, 168):
        data[f"lag_{lag}"] = data[TARGET].shift(lag)

    data["rolling_mean_24"] = (
        data[TARGET]
        .shift(1)
        .rolling(window=24, min_periods=24)
        .mean()
    )

    if dropna:
        data = data.dropna(subset=FEATURES + [TARGET]).reset_index(drop=True)

    return data


# =============================================================================
# Dataset preparation
# =============================================================================

def _validate_hourly_spacing(df: pd.DataFrame) -> None:
    """
    Detect obvious gaps in the telemetry series.

    The model can technically train with irregular timestamps, but lag_24 and
    lag_168 would no longer necessarily represent 24 hours and 7 days. It is
    safer to reject heavily irregular data than to train a misleading model.
    """
    if len(df) < 2:
        return

    intervals = (
        df["ts"]
        .sort_values()
        .diff()
        .dropna()
        .dt.total_seconds()
        / 3600
    )

    # Allow a small number of gaps. Real telemetry can occasionally miss an
    # observation, and the lag features naturally become unavailable around
    # those gaps.
    hourly_ratio = float(np.isclose(intervals, 1.0, atol=0.01).mean())

    if hourly_ratio < 0.90:
        raise ValueError(
            "Telemetry is not sufficiently hourly for the current model. "
            f"Only {hourly_ratio:.1%} of intervals are approximately one hour."
        )


def prepare_training_data(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Validate and prepare the raw dataset before model training.
    """
    _require_dataframe(df)

    if len(df) < MIN_RAW_SAMPLES:
        raise ValueError(
            f"At least {MIN_RAW_SAMPLES} raw readings are required for "
            f"training; received {len(df)}."
        )

    data = df.copy()
    data["ts"] = pd.to_datetime(data["ts"], errors="coerce", utc=True)

    if data["ts"].isna().any():
        raise ValueError("Training data contains invalid timestamps.")

    data = data.sort_values("ts").reset_index(drop=True)

    _validate_hourly_spacing(data)

    return make_features(data, dropna=True)


# =============================================================================
# Baseline
# =============================================================================

def _evaluate_baseline(
    data: pd.DataFrame,
    split: int,
) -> tuple[float, float]:
    """
    Evaluate a simple previous-hour persistence baseline.

    A machine-learning model should demonstrate value relative to a simple
    forecasting strategy rather than being evaluated in isolation.

    Baseline:
        predicted demand = previous-hour demand
    """
    y_test = data[TARGET].iloc[split:]
    baseline_prediction = data["lag_1"].iloc[split:]

    mae = mean_absolute_error(y_test, baseline_prediction)
    rmse = float(
        np.sqrt(
            mean_squared_error(
                y_test,
                baseline_prediction,
            )
        )
    )

    return float(mae), rmse


# =============================================================================
# Model construction
# =============================================================================

def build_model(
    *,
    random_state: int = DEFAULT_RANDOM_STATE,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    max_depth: int | None = DEFAULT_MAX_DEPTH,
    min_samples_leaf: int = DEFAULT_MIN_SAMPLES_LEAF,
) -> RandomForestRegressor:
    """
    Construct a fresh forecasting model.

    Keeping model construction separate from training makes unit testing and
    hyperparameter experimentation much easier.
    """
    if n_estimators <= 0:
        raise ValueError("n_estimators must be positive.")

    if max_depth is not None and max_depth <= 0:
        raise ValueError("max_depth must be positive or None.")

    if min_samples_leaf <= 0:
        raise ValueError("min_samples_leaf must be positive.")

    return RandomForestRegressor(
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        random_state=random_state,
        n_jobs=-1,
    )


# =============================================================================
# Training
# =============================================================================

def train_model(
    df: pd.DataFrame,
    *,
    model_path: Path | str = MODEL_PATH,
    test_fraction: float = 0.20,
    random_state: int = DEFAULT_RANDOM_STATE,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    max_depth: int | None = DEFAULT_MAX_DEPTH,
    min_samples_leaf: int = DEFAULT_MIN_SAMPLES_LEAF,
    model_version: str = "random_forest_v1",
) -> dict[str, Any]:
    """
    Train, evaluate, and persist the EnergyPilot forecasting model.

    The split is chronological rather than random. Randomly shuffling
    time-series observations would allow future observations to influence the
    training set and produce overly optimistic evaluation metrics.

    Returns
    -------
    dict
        JSON-friendly training metrics and model metadata.
    """
    if not 0.05 <= test_fraction <= 0.50:
        raise ValueError("test_fraction must be between 0.05 and 0.50.")

    data = prepare_training_data(df)

    if len(data) < MIN_TRAIN_SAMPLES + MIN_TEST_SAMPLES:
        raise ValueError(
            "Not enough feature-complete samples for a reliable "
            f"train/test split. Need at least "
            f"{MIN_TRAIN_SAMPLES + MIN_TEST_SAMPLES}; "
            f"received {len(data)}."
        )

    split = int(len(data) * (1.0 - test_fraction))

    if split < MIN_TRAIN_SAMPLES:
        raise ValueError(
            f"Training split contains only {split} samples; "
            f"at least {MIN_TRAIN_SAMPLES} are required."
        )

    test_size = len(data) - split

    if test_size < MIN_TEST_SAMPLES:
        raise ValueError(
            f"Test split contains only {test_size} samples; "
            f"at least {MIN_TEST_SAMPLES} are required."
        )

    X_train = data.iloc[:split][FEATURES]
    y_train = data.iloc[:split][TARGET]

    X_test = data.iloc[split:][FEATURES]
    y_test = data.iloc[split:][TARGET]

    model = build_model(
        random_state=random_state,
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
    )

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    # A power demand forecast should never be negative.
    predictions = np.clip(predictions, 0.0, None)

    mae = float(mean_absolute_error(y_test, predictions))
    rmse = float(
        np.sqrt(
            mean_squared_error(y_test, predictions)
        )
    )

    baseline_mae, baseline_rmse = _evaluate_baseline(data, split)

    metrics = ModelMetrics(
        mae_kw=mae,
        rmse_kw=rmse,
        samples=len(data),
        train_samples=len(X_train),
        test_samples=len(X_test),
        baseline_mae_kw=baseline_mae,
        baseline_rmse_kw=baseline_rmse,
    )

    artifact = ModelArtifact(
        model_version=model_version,
        target=TARGET,
        features=tuple(FEATURES),
        frequency=EXPECTED_FREQUENCY,
        random_state=random_state,
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
    )

    payload = {
        "model": model,
        "metadata": asdict(artifact),
        "metrics": metrics.to_dict(),
    }

    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Store the sklearn estimator and its metadata together. This avoids the
    # dangerous situation where a model artifact and the current FEATURE list
    # silently disagree.
    joblib.dump(payload, path)

    return {
        "metrics": metrics.to_dict(),
        "model": asdict(artifact),
        "model_path": str(path),
    }


# =============================================================================
# Model loading
# =============================================================================

def load_model(
    model_path: Path | str = MODEL_PATH,
) -> RandomForestRegressor:
    """
    Load the persisted sklearn model.

    Raises a clear error when the artifact does not exist or is incompatible
    with the current feature contract.
    """
    path = Path(model_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Forecast model was not found at '{path}'. "
            "Train the model before requesting a forecast."
        )

    try:
        payload = joblib.load(path)
    except Exception as exc:
        raise RuntimeError(
            f"Unable to load forecast model from '{path}'."
        ) from exc

    # Support the new structured artifact.
    if isinstance(payload, dict) and "model" in payload:
        model = payload["model"]
        metadata = payload.get("metadata", {})

        stored_features = metadata.get("features")

        if stored_features is not None and list(stored_features) != FEATURES:
            raise RuntimeError(
                "Saved forecast model uses a different feature contract. "
                "Retrain the model with the current FEATURES definition."
            )

        if not isinstance(model, RandomForestRegressor):
            raise TypeError(
                "Saved forecast artifact does not contain a "
                "RandomForestRegressor."
            )

        return model

    # Backward compatibility with the original EnergyPilot artifact, which
    # stored the sklearn model directly with joblib.dump(model, ...).
    if isinstance(payload, RandomForestRegressor):
        return payload

    raise TypeError(
        "Forecast model artifact has an unsupported format."
    )


def load_model_artifact(
    model_path: Path | str = MODEL_PATH,
) -> dict[str, Any]:
    """
    Load the complete model artifact including metadata and metrics.

    This is useful for diagnostics and API health endpoints without exposing
    the sklearn estimator itself.
    """
    path = Path(model_path)

    if not path.exists():
        raise FileNotFoundError(
            f"Forecast model was not found at '{path}'."
        )

    payload = joblib.load(path)

    if not isinstance(payload, dict) or "model" not in payload:
        raise RuntimeError(
            "The saved model does not contain EnergyPilot model metadata. "
            "Retrain the model."
        )

    return payload


# =============================================================================
# Inference
# =============================================================================

def predict(
    df: pd.DataFrame,
    *,
    model: RandomForestRegressor | None = None,
    model_path: Path | str = MODEL_PATH,
) -> np.ndarray:
    """
    Generate demand predictions for feature-complete rows.

    Parameters
    ----------
    df:
        Raw or feature-engineered telemetry DataFrame.

    model:
        Optional already-loaded model. Supplying one avoids repeatedly reading
        the joblib artifact when generating many forecasts.

    model_path:
        Path used only when `model` is not supplied.
    """
    if model is None:
        model = load_model(model_path)

    if not isinstance(model, RandomForestRegressor):
        raise TypeError(
            "model must be a RandomForestRegressor."
        )

    data = make_features(df, dropna=True)

    if data.empty:
        raise ValueError(
            "No feature-complete rows are available for prediction."
        )

    predictions = model.predict(data[FEATURES])

    # Random forests should not produce negative physical demand values, but
    # clipping protects the API contract even if a future model behaves
    # differently.
    return np.clip(predictions, 0.0, None)


def predict_dataframe(
    df: pd.DataFrame,
    *,
    model: RandomForestRegressor | None = None,
    model_path: Path | str = MODEL_PATH,
) -> pd.DataFrame:
    """
    Return timestamps and predictions in a frontend/API-friendly DataFrame.
    """
    data = make_features(df, dropna=True)

    if data.empty:
        raise ValueError(
            "No feature-complete rows are available for prediction."
        )

    if model is None:
        model = load_model(model_path)

    predictions = np.clip(
        model.predict(data[FEATURES]),
        0.0,
        None,
    )

    return pd.DataFrame(
        {
            "timestamp": data["ts"],
            "predicted_kw": predictions,
        }
    )


# =============================================================================
# Diagnostics
# =============================================================================

def get_feature_importance(
    model: RandomForestRegressor | None = None,
    *,
    model_path: Path | str = MODEL_PATH,
) -> pd.DataFrame:
    """
    Return Random Forest feature importance in descending order.

    This is useful for model diagnostics and portfolio demonstrations, but
    feature importance should not be interpreted as causal influence.
    """
    if model is None:
        model = load_model(model_path)

    if not hasattr(model, "feature_importances_"):
        raise TypeError(
            "The supplied model does not expose feature importances."
        )

    return (
        pd.DataFrame(
            {
                "feature": FEATURES,
                "importance": model.feature_importances_,
            }
        )
        .sort_values("importance", ascending=False)
        .reset_index(drop=True)
    )


# =============================================================================
# Backward-compatible public API
# =============================================================================

def train(df: pd.DataFrame) -> dict[str, Any]:
    """
    Backward-compatible wrapper for existing EnergyPilot code.

    Existing callers can continue using:

        train(df)

    while new code should prefer `train_model()` because it exposes the
    training configuration explicitly.
    """
    return train_model(df)


__all__ = [
    "FEATURES",
    "MODEL_PATH",
    "TARGET",
    "ModelArtifact",
    "ModelMetrics",
    "build_model",
    "get_feature_importance",
    "load_model",
    "load_model_artifact",
    "make_features",
    "predict",
    "predict_dataframe",
    "prepare_training_data",
    "train",
    "train_model",
]