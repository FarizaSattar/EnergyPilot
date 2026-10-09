"""
EnergyPilot model-training entry point.

This script is intentionally kept separate from `forecasting/model.py`.

Responsibilities:

    train_model.py
        - load historical telemetry from PostgreSQL
        - validate the requested building
        - invoke the forecasting model
        - print useful training/evaluation results

    forecasting/model.py
        - feature engineering
        - model construction
        - training
        - evaluation
        - model persistence
        - inference

    db.py
        - PostgreSQL connection management
        - database queries
        - persistence

Usage:

    python train_model.py

    python train_model.py --building-id building-001

    python train_model.py --building-id building-001 --test-fraction 0.2

    python train_model.py --building-id building-001 --model-version rf_v2

The script assumes it is executed from the backend directory:

    backend/
    ├── db.py
    ├── train_model.py
    └── forecasting/
        └── model.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# ---------------------------------------------------------------------------
# Import the project's database and forecasting layers.
#
# The script should be run as:
#
#     python train_model.py
#
# from the backend directory. This avoids the fragile `sys.path.append(...)`
# pattern used by the original script.
# ---------------------------------------------------------------------------
try:
    from db import DEFAULT_BUILDING_ID, get_conn
    from forecasting.model import (
        MODEL_PATH,
        MIN_RAW_SAMPLES,
        train_model,
    )
except ImportError as exc:
    raise ImportError(
        "Unable to import EnergyPilot backend modules. "
        "Run this script from the backend directory, for example:\n\n"
        "    cd backend\n"
        "    python train_model.py\n"
    ) from exc


# =============================================================================
# Configuration
# =============================================================================

LOGGER = logging.getLogger("energypilot.train")

DEFAULT_TEST_FRACTION = 0.20

# Only request fields actually needed by the forecasting model. Keeping the
# query narrow reduces database/network overhead and makes the training
# contract explicit.
TRAINING_COLUMNS = (
    "ts",
    "demand_kw",
    "temperature_c",
    "occupancy",
)


# =============================================================================
# Logging
# =============================================================================

def configure_logging(verbose: bool = False) -> None:
    """Configure human-readable CLI logging."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# =============================================================================
# Argument parsing
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(
        description=(
            "Train the EnergyPilot demand forecasting model "
            "using historical PostgreSQL telemetry."
        )
    )

    parser.add_argument(
        "--building-id",
        default=DEFAULT_BUILDING_ID,
        help=(
            "Building identifier to train on "
            f"(default: {DEFAULT_BUILDING_ID})."
        ),
    )

    parser.add_argument(
        "--test-fraction",
        type=float,
        default=DEFAULT_TEST_FRACTION,
        help=(
            "Fraction of chronological data reserved for evaluation "
            f"(default: {DEFAULT_TEST_FRACTION})."
        ),
    )

    parser.add_argument(
        "--model-path",
        type=Path,
        default=MODEL_PATH,
        help=(
            "Where to save the trained model artifact "
            f"(default: {MODEL_PATH})."
        ),
    )

    parser.add_argument(
        "--model-version",
        default="random_forest_v1",
        help="Version label stored with the trained model.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed logging.",
    )

    return parser


# =============================================================================
# Validation
# =============================================================================

def validate_arguments(args: argparse.Namespace) -> None:
    """Validate CLI arguments before opening the database."""
    building_id = args.building_id.strip()

    if not building_id:
        raise ValueError("--building-id cannot be empty.")

    if len(building_id) > 100:
        raise ValueError(
            "--building-id cannot exceed 100 characters."
        )

    if not 0.05 <= args.test_fraction <= 0.50:
        raise ValueError(
            "--test-fraction must be between 0.05 and 0.50."
        )

    if not args.model_version.strip():
        raise ValueError("--model-version cannot be empty.")

    if len(args.model_version) > 200:
        raise ValueError(
            "--model-version cannot exceed 200 characters."
        )


# =============================================================================
# Database access
# =============================================================================

def load_training_data(
    building_id: str,
) -> pd.DataFrame:
    """
    Load historical telemetry for one building.

    The query deliberately orders by timestamp so the forecasting layer
    receives a deterministic chronological dataset.

    The connection/transaction lifecycle remains owned by db.py.
    """
    query = """
        SELECT
            ts,
            demand_kw,
            temperature_c,
            occupancy
        FROM meter_readings
        WHERE building_id = %s
        ORDER BY ts ASC
    """

    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (building_id,))
            rows = cursor.fetchall()

    if not rows:
        raise ValueError(
            f"No meter readings were found for building '{building_id}'."
        )

    df = pd.DataFrame(
        rows,
        columns=TRAINING_COLUMNS,
    )

    return df


# =============================================================================
# Dataset diagnostics
# =============================================================================

def summarize_dataset(df: pd.DataFrame) -> dict[str, Any]:
    """Return useful diagnostics before model training."""
    if df.empty:
        return {
            "rows": 0,
            "start": None,
            "end": None,
            "duration_days": 0.0,
        }

    timestamps = pd.to_datetime(
        df["ts"],
        errors="coerce",
        utc=True,
    )

    valid_timestamps = timestamps.dropna()

    if valid_timestamps.empty:
        duration_days = 0.0
        start = None
        end = None
    else:
        start_timestamp = valid_timestamps.min()
        end_timestamp = valid_timestamps.max()

        duration_days = (
            end_timestamp - start_timestamp
        ).total_seconds() / 86400.0

        start = start_timestamp.isoformat()
        end = end_timestamp.isoformat()

    return {
        "rows": int(len(df)),
        "start": start,
        "end": end,
        "duration_days": round(duration_days, 2),
        "missing_temperature": int(df["temperature_c"].isna().sum()),
        "missing_occupancy": int(df["occupancy"].isna().sum()),
        "missing_demand": int(df["demand_kw"].isna().sum()),
    }


# =============================================================================
# Training
# =============================================================================

def train_building(
    *,
    building_id: str,
    test_fraction: float,
    model_path: Path,
    model_version: str,
) -> dict[str, Any]:
    """
    Load telemetry, train the model, and return training results.
    """
    LOGGER.info(
        "Loading telemetry for building '%s'...",
        building_id,
    )

    df = load_training_data(building_id)

    dataset_summary = summarize_dataset(df)

    LOGGER.info(
        "Loaded %d readings covering %s to %s.",
        dataset_summary["rows"],
        dataset_summary["start"],
        dataset_summary["end"],
    )

    # The model layer performs the authoritative minimum-data validation.
    # This early check provides a clearer CLI message before more expensive
    # feature engineering begins.
    if len(df) < MIN_RAW_SAMPLES:
        raise ValueError(
            f"Only {len(df)} readings are available, but at least "
            f"{MIN_RAW_SAMPLES} are required."
        )

    if dataset_summary["missing_temperature"]:
        LOGGER.warning(
            "%d readings have missing temperature telemetry. "
            "The forecasting pipeline will handle these values.",
            dataset_summary["missing_temperature"],
        )

    if dataset_summary["missing_occupancy"]:
        LOGGER.warning(
            "%d readings have missing occupancy telemetry. "
            "The forecasting pipeline will handle these values.",
            dataset_summary["missing_occupancy"],
        )

    if dataset_summary["missing_demand"]:
        LOGGER.warning(
            "%d readings have missing demand values.",
            dataset_summary["missing_demand"],
        )

    LOGGER.info("Training Random Forest forecasting model...")

    results = train_model(
        df,
        model_path=model_path,
        test_fraction=test_fraction,
        model_version=model_version,
    )

    results["building_id"] = building_id
    results["dataset"] = dataset_summary

    return results


# =============================================================================
# Output
# =============================================================================

def print_results(results: dict[str, Any]) -> None:
    """Print a concise human-readable training report."""
    metrics = results["metrics"]
    model = results["model"]
    dataset = results["dataset"]

    print()
    print("=" * 64)
    print("EnergyPilot Forecast Model Training")
    print("=" * 64)

    print()
    print("Dataset")
    print("-" * 64)
    print(f"Building:           {results['building_id']}")
    print(f"Raw readings:       {dataset['rows']}")
    print(f"Feature samples:    {metrics['samples']}")
    print(f"Training samples:   {metrics['train_samples']}")
    print(f"Test samples:       {metrics['test_samples']}")

    print(f"Start:              {dataset['start']}")
    print(f"End:                {dataset['end']}")
    print(f"Duration:           {dataset['duration_days']:.2f} days")

    print()
    print("Model")
    print("-" * 64)
    print(f"Version:            {model['model_version']}")
    print(f"Estimator:          RandomForestRegressor")
    print(f"Trees:              {model['n_estimators']}")
    print(f"Max depth:          {model['max_depth']}")
    print(f"Min samples/leaf:   {model['min_samples_leaf']}")

    print()
    print("Evaluation")
    print("-" * 64)
    print(f"Model MAE:          {metrics['mae_kw']:.4f} kW")
    print(f"Model RMSE:         {metrics['rmse_kw']:.4f} kW")

    if metrics["baseline_mae_kw"] is not None:
        print(
            f"Baseline MAE:       "
            f"{metrics['baseline_mae_kw']:.4f} kW"
        )

    if metrics["baseline_rmse_kw"] is not None:
        print(
            f"Baseline RMSE:      "
            f"{metrics['baseline_rmse_kw']:.4f} kW"
        )

    print()
    print("Artifact")
    print("-" * 64)
    print(f"Saved to:           {results['model_path']}")

    print()
    print("=" * 64)
    print("Training completed successfully.")
    print("=" * 64)
    print()


# =============================================================================
# CLI entry point
# =============================================================================

def main() -> int:
    """CLI entry point with controlled error handling."""
    parser = build_parser()
    args = parser.parse_args()

    configure_logging(args.verbose)

    try:
        validate_arguments(args)

        results = train_building(
            building_id=args.building_id.strip(),
            test_fraction=args.test_fraction,
            model_path=args.model_path,
            model_version=args.model_version.strip(),
        )

        print_results(results)

        return 0

    except KeyboardInterrupt:
        LOGGER.warning("Training cancelled by user.")
        return 130

    except Exception as exc:
        LOGGER.error("Training failed: %s", exc)

        if args.verbose:
            LOGGER.exception("Detailed training failure:")

        print()
        print(
            "Training failed. Run with --verbose for more details."
        )

        return 1


if __name__ == "__main__":
    sys.exit(main())