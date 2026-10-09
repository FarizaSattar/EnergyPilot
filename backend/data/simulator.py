"""
EnergyPilot synthetic energy-data simulator.

This module generates deterministic, physically plausible synthetic
household/building telemetry for development, testing, demonstrations,
forecasting experiments, and MQTT ingestion.

The simulator deliberately separates:

    1. Time generation
    2. Weather generation
    3. Occupancy generation
    4. End-use load generation
    5. Meter-level measurements

That makes the generated data easier to reason about and extend.

Generated schema:

    building_id
    timestamp
    demand_kw
    energy_kwh
    temperature_c
    occupancy
    hvac_kw
    lighting_kw

For hourly data:

    energy_kwh ~= demand_kw * 1 hour

The values are synthetic and should never be presented as real utility
measurements.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_BUILDING_ID = "building-001"
DEFAULT_DAYS = 30
DEFAULT_SEED = 42

HOURS_PER_DAY = 24
MIN_DAYS = 1
MAX_DAYS = 365

MIN_DEMAND_KW = 0.10
MAX_DEMAND_KW = 15.0

MIN_TEMPERATURE_C = -20.0
MAX_TEMPERATURE_C = 35.0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """
    Configuration for one synthetic building simulation.

    Keeping the parameters together makes simulations reproducible and
    avoids a large list of loosely related function arguments.
    """

    days: int = DEFAULT_DAYS
    seed: int | None = DEFAULT_SEED
    building_id: str = DEFAULT_BUILDING_ID

    # Approximate household baseline.
    base_load_kw: float = 0.45

    # HVAC characteristics.
    heating_setpoint_c: float = 19.0
    cooling_setpoint_c: float = 23.0

    # Random measurement/load variability.
    noise_std_kw: float = 0.08


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate_config(config: SimulationConfig) -> None:
    """Validate simulation parameters before generating data."""

    if isinstance(config.days, bool) or not isinstance(config.days, int):
        raise TypeError("days must be an integer.")

    if not MIN_DAYS <= config.days <= MAX_DAYS:
        raise ValueError(
            f"days must be between {MIN_DAYS} and {MAX_DAYS}."
        )

    if not isinstance(config.building_id, str):
        raise TypeError("building_id must be a string.")

    if not config.building_id.strip():
        raise ValueError("building_id cannot be empty.")

    if config.base_load_kw <= 0:
        raise ValueError("base_load_kw must be positive.")

    if config.noise_std_kw < 0:
        raise ValueError("noise_std_kw cannot be negative.")

    if config.heating_setpoint_c >= config.cooling_setpoint_c:
        raise ValueError(
            "heating_setpoint_c must be lower than "
            "cooling_setpoint_c."
        )


# ---------------------------------------------------------------------------
# Time generation
# ---------------------------------------------------------------------------

def _generate_timestamps(
    days: int,
    *,
    timezone: str = "America/Toronto",
    end: pd.Timestamp | None = None,
) -> pd.DatetimeIndex:
    """
    Generate hourly timestamps.

    A timezone-aware index is used so the simulated data has explicit
    temporal semantics when it eventually moves through MQTT/PostgreSQL.
    """
    if end is None:
        end = pd.Timestamp.now(tz=timezone).floor("h")
    else:
        end = pd.Timestamp(end)

        if end.tzinfo is None:
            end = end.tz_localize(timezone)
        else:
            end = end.tz_convert(timezone)

        end = end.floor("h")

    periods = days * HOURS_PER_DAY

    return pd.date_range(
        end=end,
        periods=periods,
        freq="h",
    )


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def _generate_temperature(
    timestamps: pd.DatetimeIndex,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Generate synthetic outdoor temperature.

    This is intentionally not a weather forecast. It provides realistic
    enough variation for testing HVAC-related analytics.
    """
    hour = timestamps.hour.to_numpy()
    day_of_year = timestamps.dayofyear.to_numpy()

    # Seasonal temperature component.
    seasonal = (
        8.0
        + 11.0
        * np.sin(
            2 * np.pi * (day_of_year - 80) / 365.25
        )
    )

    # Daily temperature cycle, with afternoon generally warmer.
    daily = (
        3.0
        * np.sin(
            2 * np.pi * (hour - 8) / 24
        )
    )

    # Small weather variability.
    noise = rng.normal(
        loc=0.0,
        scale=1.2,
        size=len(timestamps),
    )

    temperature = seasonal + daily + noise

    return np.clip(
        temperature,
        MIN_TEMPERATURE_C,
        MAX_TEMPERATURE_C,
    )


# ---------------------------------------------------------------------------
# Occupancy
# ---------------------------------------------------------------------------

def _generate_occupancy(
    timestamps: pd.DatetimeIndex,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Generate synthetic household occupancy.

    The model intentionally uses probabilities rather than a hard-coded
    schedule so the resulting signal is useful for analytics.
    """
    occupancy = np.zeros(
        len(timestamps),
        dtype=int,
    )

    for index, timestamp in enumerate(timestamps):
        hour = timestamp.hour
        weekend = timestamp.weekday() >= 5

        if weekend:
            probabilities = {
                "sleep": 0.95,
                "morning": 0.80,
                "day": 0.55,
                "evening": 0.95,
            }
        else:
            probabilities = {
                "sleep": 0.98,
                "morning": 0.70,
                "day": 0.20,
                "evening": 0.95,
            }

        if 0 <= hour < 6:
            occupied = rng.random() < probabilities["sleep"]

        elif 6 <= hour < 9:
            occupied = rng.random() < probabilities["morning"]

        elif 9 <= hour < 16:
            occupied = rng.random() < probabilities["day"]

        else:
            occupied = rng.random() < probabilities["evening"]

        if occupied:
            # Most simulated households have 1-4 occupants.
            occupancy[index] = int(
                rng.choice(
                    [1, 2, 3, 4],
                    p=[0.15, 0.50, 0.25, 0.10],
                )
            )

    return occupancy


# ---------------------------------------------------------------------------
# Base load
# ---------------------------------------------------------------------------

def _base_load(
    timestamps: pd.DatetimeIndex,
    occupancy: np.ndarray,
    config: SimulationConfig,
) -> np.ndarray:
    """
    Generate non-HVAC household demand.

    The model combines:
    - standby/base load
    - morning activity
    - evening activity
    - occupancy
    - weekend behavior
    """
    hours = timestamps.hour.to_numpy()
    weekdays = timestamps.weekday.to_numpy()

    load = np.full(
        len(timestamps),
        config.base_load_kw,
        dtype=float,
    )

    # Morning activity.
    load += np.where(
        (hours >= 6) & (hours < 9),
        0.35,
        0.0,
    )

    # Evening activity is intentionally the largest discretionary period.
    load += np.where(
        (hours >= 17) & (hours < 22),
        0.55,
        0.0,
    )

    # Overnight standby loads.
    load += np.where(
        (hours >= 0) & (hours < 6),
        0.08,
        0.0,
    )

    # Occupancy-dependent appliances/electronics.
    load += occupancy * 0.08

    # Slightly higher weekend daytime activity.
    weekend_day = (
        (weekdays >= 5)
        & (hours >= 9)
        & (hours < 17)
    )

    load += np.where(
        weekend_day,
        0.15,
        0.0,
    )

    return load


# ---------------------------------------------------------------------------
# Lighting
# ---------------------------------------------------------------------------

def _lighting_load(
    timestamps: pd.DatetimeIndex,
    occupancy: np.ndarray,
) -> np.ndarray:
    """
    Generate lighting demand.

    Lighting increases during occupied morning/evening periods and decreases
    during daytime hours.
    """
    hours = timestamps.hour.to_numpy()

    lighting = np.where(
        (hours >= 6) & (hours < 9),
        0.20,
        0.0,
    )

    lighting += np.where(
        (hours >= 17) & (hours < 23),
        0.32,
        0.0,
    )

    lighting += np.where(
        (hours < 6) | (hours >= 23),
        0.04,
        0.0,
    )

    # Unoccupied buildings/homes generally use less lighting.
    lighting *= np.where(
        occupancy > 0,
        1.0,
        0.25,
    )

    return lighting


# ---------------------------------------------------------------------------
# HVAC
# ---------------------------------------------------------------------------

def _hvac_load(
    temperature_c: np.ndarray,
    occupancy: np.ndarray,
    config: SimulationConfig,
    rng: np.random.Generator,
) -> np.ndarray:
    """
    Estimate HVAC electrical demand from outdoor temperature.

    Heating and cooling are represented separately conceptually, then
    combined into a single HVAC electrical load.

    This is deliberately a simplified model rather than a physical
    building-energy simulation.
    """
    heating_degree = np.maximum(
        config.heating_setpoint_c - temperature_c,
        0.0,
    )

    cooling_degree = np.maximum(
        temperature_c - config.cooling_setpoint_c,
        0.0,
    )

    heating_kw = (
        heating_degree * 0.11
    )

    cooling_kw = (
        cooling_degree * 0.14
    )

    # Occupancy contributes modest internal heat gains, reducing heating
    # requirements and increasing cooling requirements.
    heating_kw *= np.maximum(
        1.0 - occupancy * 0.025,
        0.75,
    )

    cooling_kw *= (
        1.0 + occupancy * 0.02
    )

    hvac = heating_kw + cooling_kw

    # HVAC equipment cycles rather than operating at perfectly constant
    # power. A bounded multiplier provides that behavior.
    cycling = rng.normal(
        loc=1.0,
        scale=0.08,
        size=len(temperature_c),
    )

    cycling = np.clip(
        cycling,
        0.75,
        1.25,
    )

    return np.maximum(
        hvac * cycling,
        0.0,
    )


# ---------------------------------------------------------------------------
# Demand / energy
# ---------------------------------------------------------------------------

def _generate_demand(
    timestamps: pd.DatetimeIndex,
    temperature_c: np.ndarray,
    occupancy: np.ndarray,
    config: SimulationConfig,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Generate end-use loads and total building demand."""

    base = _base_load(
        timestamps,
        occupancy,
        config,
    )

    lighting = _lighting_load(
        timestamps,
        occupancy,
    )

    hvac = _hvac_load(
        temperature_c,
        occupancy,
        config,
        rng,
    )

    # Small miscellaneous appliance load.
    appliance = (
        0.10
        + occupancy * 0.06
    )

    demand = (
        base
        + lighting
        + hvac
        + appliance
    )

    # Measurement / behavioral noise.
    noise = rng.normal(
        loc=0.0,
        scale=config.noise_std_kw,
        size=len(timestamps),
    )

    demand += noise

    demand = np.clip(
        demand,
        MIN_DEMAND_KW,
        MAX_DEMAND_KW,
    )

    return {
        "demand_kw": demand,
        "hvac_kw": np.maximum(hvac, 0.0),
        "lighting_kw": np.maximum(lighting, 0.0),
    }


# ---------------------------------------------------------------------------
# Public simulation API
# ---------------------------------------------------------------------------

def generate_household_data(
    days: int = DEFAULT_DAYS,
    seed: int | None = DEFAULT_SEED,
    building_id: str = DEFAULT_BUILDING_ID,
    *,
    timezone: str = "America/Toronto",
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Generate synthetic hourly household/building energy data.

    Parameters
    ----------
    days:
        Number of days to simulate.

    seed:
        Random seed. Use the same seed to reproduce identical data.
        Pass None for non-deterministic simulation.

    building_id:
        Identifier associated with the generated readings.

    timezone:
        IANA timezone used for timestamps.

    end:
        Optional simulation end timestamp. Supplying this makes tests fully
        deterministic without depending on the current clock.

    Returns
    -------
    pandas.DataFrame
        Columns:

            building_id
            timestamp
            demand_kw
            energy_kwh
            temperature_c
            occupancy
            hvac_kw
            lighting_kw
    """
    config = SimulationConfig(
        days=days,
        seed=seed,
        building_id=building_id,
    )

    _validate_config(config)

    rng = np.random.default_rng(
        config.seed
    )

    timestamps = _generate_timestamps(
        config.days,
        timezone=timezone,
        end=end,
    )

    temperature_c = _generate_temperature(
        timestamps,
        rng,
    )

    occupancy = _generate_occupancy(
        timestamps,
        rng,
    )

    loads = _generate_demand(
        timestamps,
        temperature_c,
        occupancy,
        config,
        rng,
    )

    demand_kw = loads["demand_kw"]

    # Each interval represents exactly one hour, therefore:
    #
    #     kWh = kW * 1 hour
    #
    # Keeping this relationship explicit prevents the common mistake of
    # treating instantaneous power (kW) as energy (kWh).
    energy_kwh = demand_kw.copy()

    dataframe = pd.DataFrame(
        {
            "building_id": config.building_id,
            "timestamp": timestamps,
            "demand_kw": np.round(
                demand_kw,
                3,
            ),
            "energy_kwh": np.round(
                energy_kwh,
                3,
            ),
            "temperature_c": np.round(
                temperature_c,
                2,
            ),
            "occupancy": occupancy,
            "hvac_kw": np.round(
                loads["hvac_kw"],
                3,
            ),
            "lighting_kw": np.round(
                loads["lighting_kw"],
                3,
            ),
        }
    )

    return dataframe


def generate_readings(
    days: int = DEFAULT_DAYS,
    seed: int | None = DEFAULT_SEED,
    building_id: str = DEFAULT_BUILDING_ID,
    *,
    timezone: str = "America/Toronto",
    end: pd.Timestamp | None = None,
) -> list[dict[str, object]]:
    """
    Generate simulator output in the dictionary format expected by db.py.

    This adapter is useful for simulation endpoints and tests:

        readings = generate_readings(days=30)
        insert_readings(readings)

    Keeping this conversion here means the database layer does not need to
    know anything about pandas DataFrames.
    """
    dataframe = generate_household_data(
        days=days,
        seed=seed,
        building_id=building_id,
        timezone=timezone,
        end=end,
    )

    records: list[dict[str, object]] = []

    for row in dataframe.itertuples(index=False):
        records.append(
            {
                "building_id": row.building_id,
                "ts": row.timestamp.to_pydatetime(),
                "demand_kw": float(row.demand_kw),
                "energy_kwh": float(row.energy_kwh),
                "temperature_c": float(row.temperature_c),
                "occupancy": float(row.occupancy),
                "hvac_kw": float(row.hvac_kw),
                "lighting_kw": float(row.lighting_kw),
            }
        )

    return records


def simulation_summary(
    dataframe: pd.DataFrame,
) -> dict[str, float]:
    """
    Calculate lightweight statistics for a simulated dataset.

    This is useful for the simulator/API response without putting analytics
    logic into Flask routes.
    """
    if dataframe.empty:
        return {
            "total_energy_kwh": 0.0,
            "average_demand_kw": 0.0,
            "peak_demand_kw": 0.0,
            "average_temperature_c": 0.0,
            "average_occupancy": 0.0,
        }

    return {
        "total_energy_kwh": round(
            float(dataframe["energy_kwh"].sum()),
            2,
        ),
        "average_demand_kw": round(
            float(dataframe["demand_kw"].mean()),
            2,
        ),
        "peak_demand_kw": round(
            float(dataframe["demand_kw"].max()),
            2,
        ),
        "average_temperature_c": round(
            float(dataframe["temperature_c"].mean()),
            2,
        ),
        "average_occupancy": round(
            float(dataframe["occupancy"].mean()),
            2,
        ),
    }


__all__ = [
    "SimulationConfig",
    "generate_household_data",
    "generate_readings",
    "simulation_summary",
]