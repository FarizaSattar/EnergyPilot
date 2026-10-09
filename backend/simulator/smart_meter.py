"""
EnergyPilot Home Smart-Meter Simulator.

This module simulates a residential EnergyPilot smart-meter device.

The simulator models a home's electrical demand from individual loads such
as:

    - HVAC
    - water heater
    - refrigerator
    - oven
    - dishwasher
    - washer
    - dryer
    - lighting
    - electronics
    - EV charger
    - miscellaneous loads

The simulator DOES NOT connect directly to PostgreSQL.

Instead:

    smart_meter.py
          |
          | MQTT
          v
    MQTT broker
          |
          v
    mqtt_ingestor.py
          |
          v
    PostgreSQL
          |
          +--------------------+
          |                    |
          v                    v
      Analytics          Recommendations
          |
          v
    EnergyPilot Dashboard


IMPORTANT
---------

This is synthetic data.

It represents what a future physical EnergyPilot energy-monitoring device
could measure. It must never be represented to users as actual measurements
from a real home.

The most important architectural property is that the simulator behaves like
a real telemetry source.

Today:

    Virtual Smart Meter -> MQTT -> EnergyPilot

Future:

    Physical EnergyPilot Hardware -> MQTT -> EnergyPilot

The downstream ingestion and analytics pipeline can therefore remain the
same when the physical device is eventually built.


UNIT SEMANTICS
--------------

power_kw
    Average/instantaneous electrical demand represented by the reading.

energy_kwh
    Energy consumed during the interval represented by the reading.

For a 15-minute interval:

    energy_kwh = power_kw * 0.25

The interval is configurable so this relationship is always explicit.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import signal
import socket
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import paho.mqtt.client as mqtt
from dotenv import load_dotenv


# =============================================================================
# Environment
# =============================================================================

load_dotenv()

LOGGER = logging.getLogger("energypilot.smart_meter")


# =============================================================================
# Constants
# =============================================================================

DEFAULT_HOUSEHOLD_ID = "household-001"
DEFAULT_DEVICE_ID = "energypilot-home-001"

DEFAULT_MQTT_HOST = "localhost"
DEFAULT_MQTT_PORT = 1883
DEFAULT_MQTT_KEEPALIVE = 60
DEFAULT_MQTT_QOS = 1

# How frequently the simulator publishes MQTT messages.
DEFAULT_PUBLISH_INTERVAL_SECONDS = 15

# How much real-world time one telemetry reading represents.
#
# 900 seconds = 15 minutes.
DEFAULT_METER_INTERVAL_SECONDS = 900

DEFAULT_TIMEZONE = "America/Toronto"

# Residential electrical assumptions.
DEFAULT_SERVICE_VOLTAGE_V = 240.0
DEFAULT_FREQUENCY_HZ = 60.0

# Small always-on residential load.
DEFAULT_BASE_LOAD_KW = 0.25

# Absolute minimum household demand.
DEFAULT_MIN_DEMAND_KW = 0.15

# Typical residential power factor.
DEFAULT_POWER_FACTOR = 0.96

DEFAULT_RANDOM_SEED: int | None = None

DEFAULT_TOPIC_TEMPLATE = (
    "energypilot/home/{household_id}/meter"
)

DEFAULT_STATUS_TOPIC_TEMPLATE = (
    "energypilot/home/{household_id}/meter/status"
)

DEFAULT_CLIENT_ID_PREFIX = "energypilot-smart-meter"

MIN_MQTT_PORT = 1
MAX_MQTT_PORT = 65535

MIN_QOS = 0
MAX_QOS = 2

MIN_PUBLISH_INTERVAL = 1
MAX_PUBLISH_INTERVAL = 86_400

MIN_METER_INTERVAL = 1
MAX_METER_INTERVAL = 86_400

MIN_VOLTAGE_V = 180.0
MAX_VOLTAGE_V = 260.0

MIN_FREQUENCY_HZ = 50.0
MAX_FREQUENCY_HZ = 70.0

MIN_POWER_FACTOR = 0.70
MAX_POWER_FACTOR = 1.00


# =============================================================================
# Exceptions
# =============================================================================


class SmartMeterError(Exception):
    """Base exception for smart-meter simulator failures."""


class SmartMeterConfigurationError(SmartMeterError):
    """Raised when simulator configuration is invalid."""


class SmartMeterPublishError(SmartMeterError):
    """Raised when an MQTT message cannot be published."""


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class SmartMeterConfig:
    """
    Runtime configuration for the residential smart-meter simulator.
    """

    household_id: str = DEFAULT_HOUSEHOLD_ID

    device_id: str = DEFAULT_DEVICE_ID

    mqtt_host: str = DEFAULT_MQTT_HOST

    mqtt_port: int = DEFAULT_MQTT_PORT

    mqtt_keepalive: int = DEFAULT_MQTT_KEEPALIVE

    mqtt_qos: int = DEFAULT_MQTT_QOS

    mqtt_username: str | None = None

    mqtt_password: str | None = None

    mqtt_tls_enabled: bool = False

    mqtt_tls_ca_cert: str | None = None

    topic_template: str = DEFAULT_TOPIC_TEMPLATE

    status_topic_template: str = (
        DEFAULT_STATUS_TOPIC_TEMPLATE
    )

    publish_interval_seconds: float = (
        DEFAULT_PUBLISH_INTERVAL_SECONDS
    )

    meter_interval_seconds: float = (
        DEFAULT_METER_INTERVAL_SECONDS
    )

    timezone: str = DEFAULT_TIMEZONE

    service_voltage_v: float = (
        DEFAULT_SERVICE_VOLTAGE_V
    )

    frequency_hz: float = (
        DEFAULT_FREQUENCY_HZ
    )

    base_load_kw: float = (
        DEFAULT_BASE_LOAD_KW
    )

    minimum_demand_kw: float = (
        DEFAULT_MIN_DEMAND_KW
    )

    power_factor: float = (
        DEFAULT_POWER_FACTOR
    )

    random_seed: int | None = (
        DEFAULT_RANDOM_SEED
    )

    client_id: str | None = None

    log_level: str = "INFO"

    def __post_init__(self) -> None:
        """Validate simulator configuration."""

        if not self.household_id.strip():
            raise SmartMeterConfigurationError(
                "household_id cannot be empty."
            )

        if not self.device_id.strip():
            raise SmartMeterConfigurationError(
                "device_id cannot be empty."
            )

        if not (
            MIN_MQTT_PORT
            <= self.mqtt_port
            <= MAX_MQTT_PORT
        ):
            raise SmartMeterConfigurationError(
                "mqtt_port is outside the valid range."
            )

        if not (
            0 <= self.mqtt_qos <= MAX_QOS
        ):
            raise SmartMeterConfigurationError(
                "mqtt_qos must be 0, 1, or 2."
            )

        if self.mqtt_keepalive <= 0:
            raise SmartMeterConfigurationError(
                "mqtt_keepalive must be positive."
            )

        if not (
            MIN_PUBLISH_INTERVAL
            <= self.publish_interval_seconds
            <= MAX_PUBLISH_INTERVAL
        ):
            raise SmartMeterConfigurationError(
                "publish_interval_seconds is invalid."
            )

        if not (
            MIN_METER_INTERVAL
            <= self.meter_interval_seconds
            <= MAX_METER_INTERVAL
        ):
            raise SmartMeterConfigurationError(
                "meter_interval_seconds is invalid."
            )

        numeric_non_negative = {
            "base_load_kw": self.base_load_kw,
            "minimum_demand_kw": self.minimum_demand_kw,
        }

        for name, value in numeric_non_negative.items():
            if (
                not math.isfinite(value)
                or value < 0
            ):
                raise SmartMeterConfigurationError(
                    f"{name} must be finite and non-negative."
                )

        if (
            self.minimum_demand_kw
            > self.base_load_kw
        ):
            raise SmartMeterConfigurationError(
                "minimum_demand_kw cannot exceed "
                "base_load_kw."
            )

        if not (
            MIN_VOLTAGE_V
            <= self.service_voltage_v
            <= MAX_VOLTAGE_V
        ):
            raise SmartMeterConfigurationError(
                "service_voltage_v is outside the "
                "supported residential range."
            )

        if not (
            MIN_FREQUENCY_HZ
            <= self.frequency_hz
            <= MAX_FREQUENCY_HZ
        ):
            raise SmartMeterConfigurationError(
                "frequency_hz is invalid."
            )

        if not (
            MIN_POWER_FACTOR
            <= self.power_factor
            <= MAX_POWER_FACTOR
        ):
            raise SmartMeterConfigurationError(
                "power_factor is invalid."
            )

        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise SmartMeterConfigurationError(
                f"Unknown timezone '{self.timezone}'."
            ) from exc


# =============================================================================
# Environment helpers
# =============================================================================


def _env(
    name: str,
    default: str | None = None,
) -> str | None:
    """Read and normalize an optional environment variable."""

    value = os.getenv(name)

    if value is None:
        return default

    value = value.strip()

    return value if value else default


def _env_int(
    name: str,
    default: int,
) -> int:
    """Read an integer environment variable."""

    value = _env(name)

    if value is None:
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise SmartMeterConfigurationError(
            f"{name} must be an integer."
        ) from exc


def _env_float(
    name: str,
    default: float,
) -> float:
    """Read a floating-point environment variable."""

    value = _env(name)

    if value is None:
        return default

    try:
        return float(value)
    except ValueError as exc:
        raise SmartMeterConfigurationError(
            f"{name} must be a number."
        ) from exc


def _env_bool(
    name: str,
    default: bool,
) -> bool:
    """Read a boolean environment variable."""

    value = _env(name)

    if value is None:
        return default

    normalized = value.lower()

    if normalized in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
        "off",
    }:
        return False

    raise SmartMeterConfigurationError(
        f"{name} must be a boolean."
    )


def load_config() -> SmartMeterConfig:
    """
    Load simulator configuration from environment variables.

    Supported variables:

        HOUSEHOLD_ID
        SMART_METER_DEVICE_ID

        MQTT_HOST
        MQTT_PORT
        MQTT_KEEPALIVE
        MQTT_QOS
        MQTT_USERNAME
        MQTT_PASSWORD
        MQTT_TLS_ENABLED
        MQTT_TLS_CA_CERT
        MQTT_TOPIC
        MQTT_STATUS_TOPIC
        MQTT_CLIENT_ID

        SMART_METER_PUBLISH_INTERVAL
        SMART_METER_INTERVAL_SECONDS
        SMART_METER_TIMEZONE

        SMART_METER_SERVICE_VOLTAGE_V
        SMART_METER_FREQUENCY_HZ
        SMART_METER_BASE_LOAD_KW
        SMART_METER_MIN_DEMAND_KW
        SMART_METER_POWER_FACTOR

        SMART_METER_RANDOM_SEED

        LOG_LEVEL
    """

    random_seed_raw = _env(
        "SMART_METER_RANDOM_SEED"
    )

    random_seed = (
        int(random_seed_raw)
        if random_seed_raw is not None
        else None
    )

    return SmartMeterConfig(
        household_id=_env(
            "HOUSEHOLD_ID",
            DEFAULT_HOUSEHOLD_ID,
        ),
        device_id=_env(
            "SMART_METER_DEVICE_ID",
            DEFAULT_DEVICE_ID,
        ),
        mqtt_host=_env(
            "MQTT_HOST",
            DEFAULT_MQTT_HOST,
        ),
        mqtt_port=_env_int(
            "MQTT_PORT",
            DEFAULT_MQTT_PORT,
        ),
        mqtt_keepalive=_env_int(
            "MQTT_KEEPALIVE",
            DEFAULT_MQTT_KEEPALIVE,
        ),
        mqtt_qos=_env_int(
            "MQTT_QOS",
            DEFAULT_MQTT_QOS,
        ),
        mqtt_username=_env(
            "MQTT_USERNAME"
        ),
        mqtt_password=_env(
            "MQTT_PASSWORD"
        ),
        mqtt_tls_enabled=_env_bool(
            "MQTT_TLS_ENABLED",
            False,
        ),
        mqtt_tls_ca_cert=_env(
            "MQTT_TLS_CA_CERT"
        ),
        topic_template=_env(
            "MQTT_TOPIC",
            DEFAULT_TOPIC_TEMPLATE,
        ),
        status_topic_template=_env(
            "MQTT_STATUS_TOPIC",
            DEFAULT_STATUS_TOPIC_TEMPLATE,
        ),
        publish_interval_seconds=_env_float(
            "SMART_METER_PUBLISH_INTERVAL",
            DEFAULT_PUBLISH_INTERVAL_SECONDS,
        ),
        meter_interval_seconds=_env_float(
            "SMART_METER_INTERVAL_SECONDS",
            DEFAULT_METER_INTERVAL_SECONDS,
        ),
        timezone=_env(
            "SMART_METER_TIMEZONE",
            DEFAULT_TIMEZONE,
        ),
        service_voltage_v=_env_float(
            "SMART_METER_SERVICE_VOLTAGE_V",
            DEFAULT_SERVICE_VOLTAGE_V,
        ),
        frequency_hz=_env_float(
            "SMART_METER_FREQUENCY_HZ",
            DEFAULT_FREQUENCY_HZ,
        ),
        base_load_kw=_env_float(
            "SMART_METER_BASE_LOAD_KW",
            DEFAULT_BASE_LOAD_KW,
        ),
        minimum_demand_kw=_env_float(
            "SMART_METER_MIN_DEMAND_KW",
            DEFAULT_MIN_DEMAND_KW,
        ),
        power_factor=_env_float(
            "SMART_METER_POWER_FACTOR",
            DEFAULT_POWER_FACTOR,
        ),
        random_seed=random_seed,
        client_id=_env(
            "MQTT_CLIENT_ID"
        ),
        log_level=_env(
            "LOG_LEVEL",
            "INFO",
        ),
    )


# =============================================================================
# Logging
# =============================================================================


def configure_logging(
    level: str = "INFO",
) -> None:
    """Configure application logging."""

    numeric_level = getattr(
        logging,
        level.upper(),
        logging.INFO,
    )

    logging.basicConfig(
        level=numeric_level,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
    )


# =============================================================================
# Home load model
# =============================================================================


@dataclass(frozen=True)
class HomeLoadProfile:
    """
    Appliance-level electrical load profile.

    Every value is instantaneous/average power in kW during the simulated
    interval.

    These values are intentionally separated so the simulator can later be
    upgraded to use more sophisticated appliance models.
    """

    hvac_kw: float

    water_heater_kw: float

    refrigerator_kw: float

    oven_kw: float

    dishwasher_kw: float

    washer_kw: float

    dryer_kw: float

    lighting_kw: float

    electronics_kw: float

    ev_charger_kw: float

    other_kw: float

    total_kw: float


# =============================================================================
# Home simulator
# =============================================================================


class SmartMeterSimulator:
    """
    Generate synthetic residential electrical telemetry.

    The simulator models the home internally at the appliance level, then
    exposes the aggregated electrical measurement as if it were coming from
    a real smart meter.

    This is important for EnergyPilot because it gives us "ground truth":

        true appliance loads
              ↓
        aggregate meter reading
              ↓
        analytics / ML

    Later we can deliberately hide the appliance-level information from the
    analytics layer and test whether EnergyPilot can infer inefficient loads.
    """

    def __init__(
        self,
        config: SmartMeterConfig,
    ) -> None:
        self.config = config

        self._random = random.Random(
            config.random_seed
        )

        self._timezone = ZoneInfo(
            config.timezone
        )

    # =========================================================================
    # Time
    # =========================================================================

    def _local_time(
        self,
        timestamp: datetime,
    ) -> datetime:
        """Convert a timestamp to the configured home timezone."""

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=timezone.utc
            )

        return timestamp.astimezone(
            self._timezone
        )

    # =========================================================================
    # Weather
    # =========================================================================

    def _temperature(
        self,
        timestamp: datetime,
    ) -> float:
        """
        Generate synthetic outdoor temperature.

        This is deliberately simple but produces a meaningful daily pattern.

        The future version can replace this with historical/weather API data.
        """

        local_time = self._local_time(
            timestamp
        )

        hour = (
            local_time.hour
            + local_time.minute / 60.0
        )

        # Daily temperature cycle.
        daily_cycle = math.sin(
            (
                (hour - 7.0)
                / 24.0
            )
            * 2.0
            * math.pi
        )

        noise = self._random.gauss(
            0.0,
            0.7,
        )

        # A mild shoulder-season baseline.
        temperature = (
            12.0
            + 8.0 * daily_cycle
            + noise
        )

        return round(
            temperature,
            2,
        )

    # =========================================================================
    # Occupancy
    # =========================================================================

    def _occupancy(
        self,
        timestamp: datetime,
    ) -> int:
        """
        Estimate the number of people currently home.

        This is synthetic behavioral data.

        Weekdays:
            lower occupancy during work/school hours.

        Weekends:
            higher daytime occupancy.
        """

        local_time = self._local_time(
            timestamp
        )

        hour = (
            local_time.hour
            + local_time.minute / 60.0
        )

        weekday = (
            local_time.weekday()
        )

        is_weekend = weekday >= 5

        if is_weekend:
            if 8 <= hour < 23:
                probability = 0.90
            else:
                probability = 0.65
        else:
            if 7 <= hour < 17:
                probability = 0.30
            elif 17 <= hour < 23:
                probability = 0.95
            else:
                probability = 0.75

        home = (
            self._random.random()
            < probability
        )

        if not home:
            return 0

        # Typical household size.
        return self._random.choice(
            [1, 1, 2, 2, 2, 3, 4]
        )

    # =========================================================================
    # HVAC
    # =========================================================================

    def _hvac_load(
        self,
        temperature_c: float,
        occupancy: int,
    ) -> float:
        """
        Simulate HVAC electricity consumption.

        This is intentionally more realistic than simply assigning a random
        number.

        Heating becomes more demanding below approximately 18 C.

        Cooling becomes more demanding above approximately 23 C.
        """

        heating_degree = max(
            0.0,
            18.0 - temperature_c,
        )

        cooling_degree = max(
            0.0,
            temperature_c - 23.0,
        )

        heating_load = (
            heating_degree * 0.45
        )

        cooling_load = (
            cooling_degree * 0.55
        )

        occupancy_load = (
            occupancy * 0.03
        )

        # Minimum cycling load when occupied.
        baseline = (
            0.15
            if occupancy > 0
            else 0.05
        )

        load = (
            baseline
            + heating_load
            + cooling_load
            + occupancy_load
        )

        # Occasional compressor/cycling variation.
        load *= self._random.uniform(
            0.85,
            1.15,
        )

        return max(
            0.0,
            load,
        )

    # =========================================================================
    # Water heater
    # =========================================================================

    def _water_heater_load(
        self,
        timestamp: datetime,
        occupancy: int,
    ) -> float:
        """
        Simulate an electric water heater.

        Higher demand occurs around:

            morning showers
            evening showers
            dishwashing
        """

        local_time = self._local_time(
            timestamp
        )

        hour = (
            local_time.hour
            + local_time.minute / 60.0
        )

        morning_peak = math.exp(
            -(
                (hour - 7.0)
                / 1.5
            )
            ** 2
        )

        evening_peak = math.exp(
            -(
                (hour - 20.0)
                / 2.0
            )
            ** 2
        )

        demand_factor = (
            morning_peak
            + evening_peak
        )

        if occupancy == 0:
            demand_factor *= 0.25

        # 4.5 kW heating element when active.
        probability = min(
            0.85,
            0.10
            + demand_factor * 0.30
            + occupancy * 0.03,
        )

        if self._random.random() < probability:
            return self._random.uniform(
                3.5,
                4.5,
            )

        return self._random.uniform(
            0.02,
            0.12,
        )

    # =========================================================================
    # Refrigerator
    # =========================================================================

    def _refrigerator_load(
        self,
        timestamp: datetime,
    ) -> float:
        """
        Simulate refrigerator compressor cycling.
        """

        # Small constant electronics draw.
        standby = 0.04

        compressor_running = (
            self._random.random()
            < 0.35
        )

        if compressor_running:
            return standby + self._random.uniform(
                0.08,
                0.18,
            )

        return standby

    # =========================================================================
    # Oven
    # =========================================================================

    def _oven_load(
        self,
        timestamp: datetime,
        occupancy: int,
    ) -> float:
        """Simulate electric oven/stove usage."""

        if occupancy == 0:
            return 0.0

        local_time = self._local_time(
            timestamp
        )

        hour = (
            local_time.hour
            + local_time.minute / 60.0
        )

        dinner_probability = math.exp(
            -(
                (hour - 18.5)
                / 2.0
            )
            ** 2
        )

        morning_probability = math.exp(
            -(
                (hour - 7.5)
                / 1.5
            )
            ** 2
        )

        probability = min(
            0.75,
            0.02
            + dinner_probability * 0.40
            + morning_probability * 0.12,
        )

        if self._random.random() < probability:
            return self._random.uniform(
                1.0,
                3.5,
            )

        return 0.0

    # =========================================================================
    # Dishwasher
    # =========================================================================

    def _dishwasher_load(
        self,
        timestamp: datetime,
        occupancy: int,
    ) -> float:
        """Simulate dishwasher operation."""

        if occupancy == 0:
            return 0.0

        local_time = self._local_time(
            timestamp
        )

        hour = local_time.hour

        evening = (
            19 <= hour <= 23
        )

        if evening and (
            self._random.random()
            < 0.18
        ):
            return self._random.uniform(
                1.0,
                1.8,
            )

        return 0.0

    # =========================================================================
    # Washing machine
    # =========================================================================

    def _washer_load(
        self,
        timestamp: datetime,
        occupancy: int,
    ) -> float:
        """Simulate washing machine operation."""

        if occupancy == 0:
            return 0.0

        local_time = self._local_time(
            timestamp
        )

        hour = local_time.hour

        preferred_hours = (
            9 <= hour <= 16
        )

        if preferred_hours and (
            self._random.random()
            < 0.06
        ):
            return self._random.uniform(
                0.4,
                0.8,
            )

        return 0.0

    # =========================================================================
    # Dryer
    # =========================================================================

    def _dryer_load(
        self,
        timestamp: datetime,
        occupancy: int,
    ) -> float:
        """Simulate electric dryer operation."""

        if occupancy == 0:
            return 0.0

        local_time = self._local_time(
            timestamp
        )

        hour = local_time.hour

        evening = (
            17 <= hour <= 22
        )

        if evening and (
            self._random.random()
            < 0.05
        ):
            return self._random.uniform(
                3.5,
                5.0,
            )

        return 0.0

    # =========================================================================
    # Lighting
    # =========================================================================

    def _lighting_load(
        self,
        timestamp: datetime,
        occupancy: int,
    ) -> float:
        """
        Simulate residential lighting.

        Lighting increases:

            - after sunset
            - when occupants are home
        """

        local_time = self._local_time(
            timestamp
        )

        hour = (
            local_time.hour
            + local_time.minute / 60.0
        )

        if occupancy == 0:
            return 0.01

        # Evening lighting.
        if (
            hour >= 17
            or hour < 7
        ):
            base = 0.15
        else:
            base = 0.05

        occupancy_component = (
            occupancy * 0.04
        )

        return (
            base
            + occupancy_component
        )

    # =========================================================================
    # Electronics
    # =========================================================================

    def _electronics_load(
        self,
        timestamp: datetime,
        occupancy: int,
    ) -> float:
        """Simulate televisions, computers, routers, chargers, etc."""

        local_time = self._local_time(
            timestamp
        )

        hour = (
            local_time.hour
            + local_time.minute / 60.0
        )

        base = 0.10

        evening_component = (
            0.30
            if 18 <= hour <= 23
            else 0.10
        )

        occupancy_component = (
            occupancy * 0.08
        )

        return (
            base
            + evening_component
            + occupancy_component
        )

    # =========================================================================
    # EV charger
    # =========================================================================

    def _ev_charger_load(
        self,
        timestamp: datetime,
        occupancy: int,
    ) -> float:
        """
        Simulate a home EV charger.

        The charger intentionally prefers overnight hours.

        This gives EnergyPilot something useful to optimize later:

            "Move EV charging outside peak hours."
        """

        local_time = self._local_time(
            timestamp
        )

        hour = (
            local_time.hour
            + local_time.minute / 60.0
        )

        overnight = (
            hour >= 23
            or hour < 7
        )

        evening_peak = (
            17 <= hour < 21
        )

        if overnight:
            if (
                self._random.random()
                < 0.40
            ):
                return self._random.uniform(
                    5.0,
                    7.2,
                )

        # Occasionally simulate inefficient peak-hour charging.
        if evening_peak:
            if (
                self._random.random()
                < 0.06
            ):
                return self._random.uniform(
                    5.0,
                    7.2,
                )

        return 0.0

    # =========================================================================
    # Other loads
    # =========================================================================

    def _other_load(
        self,
        occupancy: int,
    ) -> float:
        """
        Miscellaneous residential loads:

            fans
            pumps
            small appliances
            smart-home devices
            standby electronics
        """

        return max(
            0.02,
            self.config.base_load_kw
            + occupancy * 0.025
            + self._random.gauss(
                0.0,
                0.03,
            ),
        )

    # =========================================================================
    # Appliance aggregation
    # =========================================================================

    def _generate_load_profile(
        self,
        timestamp: datetime,
    ) -> tuple[
        HomeLoadProfile,
        float,
        int,
    ]:
        """
        Generate the complete appliance-level load profile.

        Returns:

            profile
            outdoor temperature
            occupancy
        """

        temperature = self._temperature(
            timestamp
        )

        occupancy = self._occupancy(
            timestamp
        )

        hvac_kw = self._hvac_load(
            temperature,
            occupancy,
        )

        water_heater_kw = (
            self._water_heater_load(
                timestamp,
                occupancy,
            )
        )

        refrigerator_kw = (
            self._refrigerator_load(
                timestamp
            )
        )

        oven_kw = self._oven_load(
            timestamp,
            occupancy,
        )

        dishwasher_kw = (
            self._dishwasher_load(
                timestamp,
                occupancy,
            )
        )

        washer_kw = self._washer_load(
            timestamp,
            occupancy,
        )

        dryer_kw = self._dryer_load(
            timestamp,
            occupancy,
        )

        lighting_kw = (
            self._lighting_load(
                timestamp,
                occupancy,
            )
        )

        electronics_kw = (
            self._electronics_load(
                timestamp,
                occupancy,
            )
        )

        ev_charger_kw = (
            self._ev_charger_load(
                timestamp,
                occupancy,
            )
        )

        other_kw = self._other_load(
            occupancy
        )

        total_kw = (
            hvac_kw
            + water_heater_kw
            + refrigerator_kw
            + oven_kw
            + dishwasher_kw
            + washer_kw
            + dryer_kw
            + lighting_kw
            + electronics_kw
            + ev_charger_kw
            + other_kw
        )

        profile = HomeLoadProfile(
            hvac_kw=hvac_kw,
            water_heater_kw=water_heater_kw,
            refrigerator_kw=refrigerator_kw,
            oven_kw=oven_kw,
            dishwasher_kw=dishwasher_kw,
            washer_kw=washer_kw,
            dryer_kw=dryer_kw,
            lighting_kw=lighting_kw,
            electronics_kw=electronics_kw,
            ev_charger_kw=ev_charger_kw,
            other_kw=other_kw,
            total_kw=total_kw,
        )

        return (
            profile,
            temperature,
            occupancy,
        )

    # =========================================================================
    # Electrical measurement model
    # =========================================================================

    def _voltage(
        self,
    ) -> float:
        """Simulate small residential service-voltage variation."""

        voltage = (
            self.config.service_voltage_v
            + self._random.gauss(
                0.0,
                1.2,
            )
        )

        return max(
            MIN_VOLTAGE_V,
            min(
                MAX_VOLTAGE_V,
                voltage,
            ),
        )

    def _frequency(
        self,
    ) -> float:
        """Simulate small grid-frequency variation."""

        frequency = (
            self.config.frequency_hz
            + self._random.gauss(
                0.0,
                0.015,
            )
        )

        return max(
            MIN_FREQUENCY_HZ,
            min(
                MAX_FREQUENCY_HZ,
                frequency,
            ),
        )

    def _power_factor(
        self,
        profile: HomeLoadProfile,
    ) -> float:
        """
        Simulate household power factor.

        Motor-driven loads such as HVAC and refrigeration slightly reduce
        power factor.
        """

        motor_load = (
            profile.hvac_kw
            + profile.refrigerator_kw
        )

        penalty = min(
            0.10,
            motor_load * 0.006,
        )

        pf = (
            self.config.power_factor
            - penalty
            + self._random.gauss(
                0.0,
                0.005,
            )
        )

        return max(
            MIN_POWER_FACTOR,
            min(
                MAX_POWER_FACTOR,
                pf,
            ),
        )

    def _current(
        self,
        power_kw: float,
        voltage_v: float,
        power_factor: float,
    ) -> float:
        """
        Estimate service current.

        Simplified single-equivalent-load relationship:

            I = P / (V * PF)

        For the simulated residential system we use the 240 V service
        voltage as the equivalent measurement point.
        """

        power_w = (
            power_kw * 1000.0
        )

        denominator = (
            voltage_v
            * power_factor
        )

        if denominator <= 0:
            return 0.0

        return power_w / denominator

    # =========================================================================
    # Reading generation
    # =========================================================================

    def generate_reading(
        self,
        timestamp: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Generate one smart-meter telemetry reading.

        The payload contains:

            device identity
            timestamp
            electrical measurements
            environmental/behavioral context
            appliance ground truth
            source metadata
        """

        if timestamp is None:
            timestamp = datetime.now(
                timezone.utc
            )

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=timezone.utc
            )

        (
            profile,
            temperature_c,
            occupancy,
        ) = self._generate_load_profile(
            timestamp
        )

        power_kw = max(
            self.config.minimum_demand_kw,
            profile.total_kw,
        )

        voltage_v = self._voltage()

        frequency_hz = self._frequency()

        power_factor = (
            self._power_factor(profile)
        )

        current_a = self._current(
            power_kw,
            voltage_v,
            power_factor,
        )

        interval_hours = (
            self.config.meter_interval_seconds
            / 3600.0
        )

        energy_kwh = (
            power_kw
            * interval_hours
        )

        payload: dict[str, Any] = {
            # ---------------------------------------------------------------
            # Device identity
            # ---------------------------------------------------------------

            "device_id": (
                self.config.device_id
            ),

            "household_id": (
                self.config.household_id
            ),

            "timestamp": (
                timestamp.astimezone(
                    timezone.utc
                ).isoformat()
            ),

            # ---------------------------------------------------------------
            # Core smart-meter measurements
            # ---------------------------------------------------------------

            "voltage_v": round(
                voltage_v,
                2,
            ),

            "current_a": round(
                current_a,
                2,
            ),

            "power_kw": round(
                power_kw,
                3,
            ),

            # Backwards-compatible alias for the previous simulator.
            "demand_kw": round(
                power_kw,
                3,
            ),

            "energy_kwh": round(
                energy_kwh,
                4,
            ),

            "power_factor": round(
                power_factor,
                4,
            ),

            "frequency_hz": round(
                frequency_hz,
                3,
            ),

            "interval_seconds": (
                self.config.meter_interval_seconds
            ),

            # ---------------------------------------------------------------
            # Home context
            # ---------------------------------------------------------------

            "temperature_c": round(
                temperature_c,
                2,
            ),

            "occupancy": occupancy,

            # ---------------------------------------------------------------
            # Appliance ground truth
            #
            # IMPORTANT:
            # These fields are available to the simulator for development and
            # ML validation.
            #
            # The eventual physical smart meter will NOT directly measure
            # these individual values.
            # ---------------------------------------------------------------

            "hvac_kw": round(
                profile.hvac_kw,
                3,
            ),

            "water_heater_kw": round(
                profile.water_heater_kw,
                3,
            ),

            "refrigerator_kw": round(
                profile.refrigerator_kw,
                3,
            ),

            "oven_kw": round(
                profile.oven_kw,
                3,
            ),

            "dishwasher_kw": round(
                profile.dishwasher_kw,
                3,
            ),

            "washer_kw": round(
                profile.washer_kw,
                3,
            ),

            "dryer_kw": round(
                profile.dryer_kw,
                3,
            ),

            "lighting_kw": round(
                profile.lighting_kw,
                3,
            ),

            "electronics_kw": round(
                profile.electronics_kw,
                3,
            ),

            "ev_charger_kw": round(
                profile.ev_charger_kw,
                3,
            ),

            "other_kw": round(
                profile.other_kw,
                3,
            ),

            # ---------------------------------------------------------------
            # Metadata
            # ---------------------------------------------------------------

            "source": "simulator",

            "simulation": True,

            "telemetry_id": str(
                uuid.uuid4()
            ),
        }

        self._validate_reading(
            payload
        )

        return payload

    # =========================================================================
    # Validation
    # =========================================================================

    @staticmethod
    def _validate_reading(
        payload: Mapping[str, Any],
    ) -> None:
        """Validate a generated telemetry payload."""

        required_fields = {
            "device_id",
            "household_id",
            "timestamp",
            "voltage_v",
            "current_a",
            "power_kw",
            "energy_kwh",
            "power_factor",
            "frequency_hz",
        }

        missing = (
            required_fields
            - payload.keys()
        )

        if missing:
            raise SmartMeterError(
                "Generated reading is missing "
                f"fields: {sorted(missing)}"
            )

        numeric_fields = {
            "voltage_v",
            "current_a",
            "power_kw",
            "energy_kwh",
            "power_factor",
            "frequency_hz",
            "temperature_c",
            "hvac_kw",
            "water_heater_kw",
            "refrigerator_kw",
            "oven_kw",
            "dishwasher_kw",
            "washer_kw",
            "dryer_kw",
            "lighting_kw",
            "electronics_kw",
            "ev_charger_kw",
            "other_kw",
        }

        for field in numeric_fields:
            value = payload.get(field)

            if value is None:
                continue

            if (
                not isinstance(
                    value,
                    (int, float),
                )
                or isinstance(
                    value,
                    bool,
                )
            ):
                raise SmartMeterError(
                    f"{field} must be numeric."
                )

            if not math.isfinite(
                float(value)
            ):
                raise SmartMeterError(
                    f"{field} must be finite."
                )

            if float(value) < 0 and field != "temperature_c":
                raise SmartMeterError(
                    f"{field} cannot be negative."
                )

        if payload["power_kw"] < 0:
            raise SmartMeterError(
                "power_kw cannot be negative."
            )

        if payload["energy_kwh"] < 0:
            raise SmartMeterError(
                "energy_kwh cannot be negative."
            )

        if not (
            MIN_POWER_FACTOR
            <= payload["power_factor"]
            <= MAX_POWER_FACTOR
        ):
            raise SmartMeterError(
                "power_factor is outside the "
                "supported range."
            )


# =============================================================================
# MQTT Publisher
# =============================================================================


class SmartMeterPublisher:
    """
    MQTT transport for the smart-meter simulator.

    MQTT is deliberately isolated from the simulation model.
    """

    def __init__(
        self,
        config: SmartMeterConfig,
    ) -> None:
        self.config = config

        client_id = (
            config.client_id
            or self._default_client_id()
        )

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )

        self.client.on_connect = (
            self._on_connect
        )

        self.client.on_disconnect = (
            self._on_disconnect
        )

        if (
            config.mqtt_username
            is not None
        ):
            self.client.username_pw_set(
                config.mqtt_username,
                config.mqtt_password,
            )

        if config.mqtt_tls_enabled:
            if config.mqtt_tls_ca_cert:
                self.client.tls_set(
                    ca_certs=(
                        config.mqtt_tls_ca_cert
                    )
                )
            else:
                self.client.tls_set()

        # MQTT Last Will.
        self.client.will_set(
            self.status_topic,
            payload=json.dumps(
                {
                    "device_id": (
                        config.device_id
                    ),
                    "household_id": (
                        config.household_id
                    ),
                    "status": "offline",
                    "source": "simulator",
                    "timestamp": (
                        datetime.now(
                            timezone.utc
                        ).isoformat()
                    ),
                },
                separators=(",", ":"),
            ),
            qos=config.mqtt_qos,
            retain=True,
        )

    def _default_client_id(
        self,
    ) -> str:
        """Create a host-specific MQTT client ID."""

        hostname = socket.gethostname()

        return (
            f"{DEFAULT_CLIENT_ID_PREFIX}-"
            f"{self.config.device_id}-"
            f"{hostname}"
        )

    @property
    def topic(self) -> str:
        """Resolve the telemetry topic."""

        return self.config.topic_template.format(
            household_id=(
                self.config.household_id
            ),
            device_id=(
                self.config.device_id
            ),
        )

    @property
    def status_topic(self) -> str:
        """Resolve the device status topic."""

        return self.config.status_topic_template.format(
            household_id=(
                self.config.household_id
            ),
            device_id=(
                self.config.device_id
            ),
        )

    def connect(self) -> None:
        """Connect to the MQTT broker."""

        LOGGER.info(
            "Connecting to MQTT broker %s:%d.",
            self.config.mqtt_host,
            self.config.mqtt_port,
        )

        try:
            self.client.connect(
                self.config.mqtt_host,
                self.config.mqtt_port,
                self.config.mqtt_keepalive,
            )
        except (
            OSError,
            mqtt.MQTTException,
        ) as exc:
            raise SmartMeterError(
                "Unable to connect to MQTT broker."
            ) from exc

        self.client.loop_start()

        # Give the network loop a moment to establish the connection.
        time.sleep(0.1)

        self.publish_status(
            "online"
        )

    def disconnect(self) -> None:
        """Publish offline status and disconnect cleanly."""

        try:
            self.publish_status(
                "offline"
            )
        except Exception:
            LOGGER.debug(
                "Unable to publish offline status.",
                exc_info=True,
            )

        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()

    def publish(
        self,
        payload: Mapping[str, Any],
    ) -> None:
        """Publish one telemetry reading."""

        try:
            message = json.dumps(
                dict(payload),
                separators=(",", ":"),
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise SmartMeterPublishError(
                "Unable to serialize meter payload."
            ) from exc

        result = self.client.publish(
            self.topic,
            message,
            qos=self.config.mqtt_qos,
        )

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise SmartMeterPublishError(
                "MQTT publish failed with "
                f"return code {result.rc}."
            )

        LOGGER.debug(
            "Published meter telemetry to %s.",
            self.topic,
        )

    def publish_status(
        self,
        status: str,
    ) -> None:
        """Publish device lifecycle status."""

        payload = {
            "device_id": (
                self.config.device_id
            ),
            "household_id": (
                self.config.household_id
            ),
            "status": status,
            "source": "simulator",
            "timestamp": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        }

        result = self.client.publish(
            self.status_topic,
            json.dumps(
                payload,
                separators=(",", ":"),
            ),
            qos=self.config.mqtt_qos,
            retain=True,
        )

        if (
            result.rc
            != mqtt.MQTT_ERR_SUCCESS
        ):
            LOGGER.warning(
                "Unable to publish device status: %s",
                result.rc,
            )

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        """Handle MQTT connection event."""

        if reason_code == 0:
            LOGGER.info(
                "Connected to MQTT broker."
            )
        else:
            LOGGER.error(
                "MQTT connection failed: %s",
                reason_code,
            )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        """Handle MQTT disconnect event."""

        if reason_code != 0:
            LOGGER.warning(
                "MQTT connection lost: %s",
                reason_code,
            )
        else:
            LOGGER.info(
                "Disconnected from MQTT broker."
            )


# =============================================================================
# Application
# =============================================================================


class SmartMeterApplication:
    """
    Coordinate:

        home simulation
        MQTT publication
        graceful shutdown
    """

    def __init__(
        self,
        config: SmartMeterConfig,
    ) -> None:
        self.config = config

        self.simulator = (
            SmartMeterSimulator(
                config
            )
        )

        self.publisher = (
            SmartMeterPublisher(
                config
            )
        )

        self._running = True

        # Timestamp used to simulate a continuous household timeline.
        self._simulation_timestamp = (
            datetime.now(
                timezone.utc
            )
        )

    def stop(
        self,
        *_args: Any,
    ) -> None:
        """Request graceful application shutdown."""

        LOGGER.info(
            "Shutdown requested."
        )

        self._running = False

    def run_once(
        self,
    ) -> dict[str, Any]:
        """
        Generate and publish exactly one reading.

        This is useful for:

            - smoke tests
            - CI
            - debugging
            - manually testing mqtt_ingestor.py
        """

        payload = (
            self.simulator.generate_reading(
                timestamp=(
                    self._simulation_timestamp
                )
            )
        )

        self.publisher.publish(
            payload
        )

        LOGGER.info(
            "Published home telemetry: "
            "household=%s device=%s "
            "power=%.3f kW "
            "energy=%.4f kWh "
            "voltage=%.2f V "
            "current=%.2f A",
            payload["household_id"],
            payload["device_id"],
            payload["power_kw"],
            payload["energy_kwh"],
            payload["voltage_v"],
            payload["current_a"],
        )

        # Move the simulated meter forward by the interval it represents.
        self._simulation_timestamp += (
            timedelta(
                seconds=(
                    self.config
                    .meter_interval_seconds
                )
            )
        )

        return payload

    def run(
        self,
    ) -> None:
        """Run the continuous smart-meter simulator."""

        self.publisher.connect()

        LOGGER.info(
            "EnergyPilot home smart-meter "
            "simulator running."
        )

        LOGGER.info(
            "Household: %s",
            self.config.household_id,
        )

        LOGGER.info(
            "Device: %s",
            self.config.device_id,
        )

        LOGGER.info(
            "Telemetry topic: %s",
            self.publisher.topic,
        )

        LOGGER.info(
            "Publishing every %.1f seconds.",
            self.config.publish_interval_seconds,
        )

        LOGGER.info(
            "Each reading represents %.1f minutes.",
            (
                self.config
                .meter_interval_seconds
                / 60.0
            ),
        )

        try:
            while self._running:
                started = time.monotonic()

                try:
                    self.run_once()

                except SmartMeterPublishError:
                    LOGGER.exception(
                        "Failed to publish "
                        "smart-meter reading."
                    )

                except SmartMeterError:
                    LOGGER.exception(
                        "Failed to generate "
                        "smart-meter reading."
                    )

                elapsed = (
                    time.monotonic()
                    - started
                )

                sleep_time = max(
                    0.0,
                    (
                        self.config
                        .publish_interval_seconds
                        - elapsed
                    ),
                )

                # Sleep in short chunks so shutdown signals are handled
                # promptly.
                end_time = (
                    time.monotonic()
                    + sleep_time
                )

                while (
                    self._running
                    and time.monotonic()
                    < end_time
                ):
                    remaining = (
                        end_time
                        - time.monotonic()
                    )

                    time.sleep(
                        min(
                            0.5,
                            max(
                                0.0,
                                remaining,
                            ),
                        )
                    )

        finally:
            self.publisher.disconnect()

            LOGGER.info(
                "EnergyPilot home smart-meter "
                "simulator stopped."
            )


# =============================================================================
# Entry point
# =============================================================================


def main() -> int:
    """Application entry point."""

    try:
        config = load_config()

        configure_logging(
            config.log_level
        )

        application = (
            SmartMeterApplication(
                config
            )
        )

        signal.signal(
            signal.SIGINT,
            application.stop,
        )

        signal.signal(
            signal.SIGTERM,
            application.stop,
        )

        application.run()

        return 0

    except SmartMeterConfigurationError as exc:
        print(
            f"Configuration error: {exc}"
        )

        return 2

    except SmartMeterError as exc:
        LOGGER.exception(
            "Smart-meter simulator failed: %s",
            exc,
        )

        return 1

    except KeyboardInterrupt:
        return 0

    except Exception:
        LOGGER.exception(
            "Unexpected smart-meter simulator failure."
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )