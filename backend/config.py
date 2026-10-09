"""
EnergyPilot application configuration.

This module is the single source of truth for application configuration.

Telemetry contract
------------------
Every EnergyPilot telemetry reading uses:

    building_id      : string, required
    timestamp        : ISO-8601 UTC timestamp, required
    demand_kw        : finite float >= 0, required
    energy_kwh       : finite float >= 0, required
    temperature_c    : finite float | null
    occupancy        : integer >= 0 | null
    hvac_kw          : finite float >= 0 | null
    lighting_kw      : finite float >= 0 | null

Database
--------
PostgreSQL is the canonical persistence layer.
"""

from __future__ import annotations

import os
from pathlib import Path


# ============================================================================
# Environment helpers
# ============================================================================

def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default

    value = value.strip()
    return value if value else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None or value.strip() == "":
        return default

    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer. Received: {value!r}"
        ) from exc


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)

    if value is None or value.strip() == "":
        return default

    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a number. Received: {value!r}"
        ) from exc


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None or value.strip() == "":
        return default

    normalized = value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(
        f"{name} must be true/false. Received: {value!r}"
    )


# ============================================================================
# Application
# ============================================================================

APP_NAME = _env_str(
    "APP_NAME",
    "EnergyPilot API",
)

APP_VERSION = _env_str(
    "APP_VERSION",
    "2.0.0",
)

ENVIRONMENT = _env_str(
    "ENVIRONMENT",
    "development",
)

DEBUG = _env_bool(
    "DEBUG",
    ENVIRONMENT == "development",
)

DEFAULT_HOME_ID = _env_str(
    "DEFAULT_HOME_ID",
    "building-001",
)


# ============================================================================
# Paths
# ============================================================================

BASE_DIR = Path(
    os.getenv(
        "ENERGYPILOT_BASE_DIR",
        Path(__file__).resolve().parent,
    )
).resolve()

UPLOAD_FOLDER = Path(
    _env_str(
        "UPLOAD_FOLDER",
        str(BASE_DIR / "uploads"),
    )
).resolve()


# ============================================================================
# PostgreSQL
# ============================================================================

DATABASE_URL = _env_str(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/energypilot",
)

DB_HOST = _env_str(
    "DB_HOST",
    "localhost",
)

DB_PORT = _env_int(
    "DB_PORT",
    5432,
)

DB_NAME = _env_str(
    "DB_NAME",
    "energypilot",
)

DB_USER = _env_str(
    "DB_USER",
    "postgres",
)

DB_PASSWORD = os.getenv(
    "DB_PASSWORD",
    "postgres",
)

DB_POOL_MIN = _env_int(
    "DB_POOL_MIN",
    1,
)

DB_POOL_MAX = _env_int(
    "DB_POOL_MAX",
    10,
)


# ============================================================================
# Flask / API
# ============================================================================

API_HOST = _env_str(
    "API_HOST",
    _env_str("HOST", "127.0.0.1"),
)

API_PORT = _env_int(
    "API_PORT",
    _env_int("PORT", 5000),
)

HOST = API_HOST
PORT = API_PORT

CORS_ORIGINS = [
    origin.strip()
    for origin in _env_str(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173",
    ).split(",")
    if origin.strip()
]


# ============================================================================
# API limits
# ============================================================================

DEFAULT_READINGS_LIMIT = _env_int(
    "DEFAULT_READINGS_LIMIT",
    500,
)

MAX_READINGS_LIMIT = _env_int(
    "MAX_READINGS_LIMIT",
    5000,
)

DEFAULT_HISTORY_HOURS = _env_int(
    "DEFAULT_HISTORY_HOURS",
    24,
)

MAX_HISTORY_HOURS = _env_int(
    "MAX_HISTORY_HOURS",
    24 * 31,
)

MAX_UPLOAD_MB = _env_int(
    "MAX_UPLOAD_MB",
    10,
)

MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

MAX_UPLOAD_ROWS = _env_int(
    "MAX_UPLOAD_ROWS",
    250_000,
)

SUPPORTED_UPLOAD_EXTENSIONS = {
    ".csv",
}


# ============================================================================
# Forecast / simulation
# ============================================================================

DEFAULT_FORECAST_DAYS = _env_int(
    "DEFAULT_FORECAST_DAYS",
    7,
)

MAX_FORECAST_DAYS = _env_int(
    "MAX_FORECAST_DAYS",
    90,
)

DEFAULT_SIMULATION_DAYS = _env_int(
    "DEFAULT_SIMULATION_DAYS",
    30,
)

MAX_SIMULATION_DAYS = _env_int(
    "MAX_SIMULATION_DAYS",
    365,
)


# ============================================================================
# Energy conventions
# ============================================================================

ENERGY_UNIT = "kWh"
POWER_UNIT = "kW"
CURRENCY = "CAD"

TIMEZONE = _env_str(
    "TIMEZONE",
    "America/Toronto",
)

NEGATIVE_ENERGY_ALLOWED = False

FORECAST_PERIODS_PER_DAY = 24


# ============================================================================
# Pricing
# ============================================================================

PRICING_PLANS = {
    "tou": "Time-of-Use",
    "tiered": "Tiered",
    "ulo": "Ultra-Low Overnight",
}

DEFAULT_PRICING_PLAN = _env_str(
    "DEFAULT_PRICING_PLAN",
    "tou",
).lower()


# ============================================================================
# Telemetry contract
# ============================================================================

TELEMETRY_SCHEMA_VERSION = "1.0"

TELEMETRY_REQUIRED_FIELDS = (
    "building_id",
    "timestamp",
    "demand_kw",
    "energy_kwh",
)

TELEMETRY_OPTIONAL_FIELDS = (
    "temperature_c",
    "occupancy",
    "hvac_kw",
    "lighting_kw",
)

TELEMETRY_FIELDS = (
    "building_id",
    "timestamp",
    "demand_kw",
    "energy_kwh",
    "temperature_c",
    "occupancy",
    "hvac_kw",
    "lighting_kw",
)

TELEMETRY_SOURCE_MQTT = "mqtt"
TELEMETRY_SOURCE_CSV = "csv"
TELEMETRY_SOURCE_API = "api"
TELEMETRY_SOURCE_SIMULATION = "simulation"

TELEMETRY_SOURCES = {
    TELEMETRY_SOURCE_MQTT,
    TELEMETRY_SOURCE_CSV,
    TELEMETRY_SOURCE_API,
    TELEMETRY_SOURCE_SIMULATION,
}


# ============================================================================
# MQTT
# ============================================================================

MQTT_HOST = _env_str(
    "MQTT_HOST",
    "localhost",
)

MQTT_PORT = _env_int(
    "MQTT_PORT",
    1883,
)

MQTT_KEEPALIVE = _env_int(
    "MQTT_KEEPALIVE",
    60,
)

MQTT_TOPIC = _env_str(
    "MQTT_TOPIC",
    "building/+/meter",
)

MQTT_QOS = _env_int(
    "MQTT_QOS",
    1,
)

MQTT_CLIENT_ID = _env_str(
    "MQTT_CLIENT_ID",
    "energypilot-ingestor",
)

MQTT_USERNAME = os.getenv(
    "MQTT_USERNAME",
)

MQTT_PASSWORD = os.getenv(
    "MQTT_PASSWORD",
)

MQTT_TLS_ENABLED = _env_bool(
    "MQTT_TLS_ENABLED",
    False,
)

MQTT_TLS_CA_CERT = os.getenv(
    "MQTT_TLS_CA_CERT"
)

MQTT_STATUS_TOPIC = _env_str(
    "MQTT_STATUS_TOPIC",
    "energypilot/ingestor/status",
)


# ============================================================================
# Error handling
# ============================================================================

EXPOSE_INTERNAL_ERRORS = _env_bool(
    "EXPOSE_INTERNAL_ERRORS",
    False,
)


# ============================================================================
# Validation
# ============================================================================

def validate_config() -> None:
    """Validate application configuration at startup."""

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL cannot be empty.")

    if DB_POOL_MIN < 1:
        raise ValueError("DB_POOL_MIN must be >= 1.")

    if DB_POOL_MAX < DB_POOL_MIN:
        raise ValueError(
            "DB_POOL_MAX must be >= DB_POOL_MIN."
        )

    if API_PORT < 1 or API_PORT > 65535:
        raise ValueError(
            "API_PORT must be between 1 and 65535."
        )

    if MQTT_PORT < 1 or MQTT_PORT > 65535:
        raise ValueError(
            "MQTT_PORT must be between 1 and 65535."
        )

    if MQTT_QOS not in {0, 1, 2}:
        raise ValueError(
            "MQTT_QOS must be 0, 1, or 2."
        )

    if DEFAULT_READINGS_LIMIT < 1:
        raise ValueError(
            "DEFAULT_READINGS_LIMIT must be >= 1."
        )

    if MAX_READINGS_LIMIT < DEFAULT_READINGS_LIMIT:
        raise ValueError(
            "MAX_READINGS_LIMIT must be >= DEFAULT_READINGS_LIMIT."
        )

    if DEFAULT_HISTORY_HOURS < 1:
        raise ValueError(
            "DEFAULT_HISTORY_HOURS must be >= 1."
        )

    if MAX_HISTORY_HOURS < DEFAULT_HISTORY_HOURS:
        raise ValueError(
            "MAX_HISTORY_HOURS must be >= DEFAULT_HISTORY_HOURS."
        )

    if MAX_UPLOAD_MB < 1:
        raise ValueError(
            "MAX_UPLOAD_MB must be >= 1."
        )

    if MAX_UPLOAD_ROWS < 1:
        raise ValueError(
            "MAX_UPLOAD_ROWS must be >= 1."
        )

    if DEFAULT_FORECAST_DAYS < 1:
        raise ValueError(
            "DEFAULT_FORECAST_DAYS must be >= 1."
        )

    if MAX_FORECAST_DAYS < DEFAULT_FORECAST_DAYS:
        raise ValueError(
            "MAX_FORECAST_DAYS must be >= DEFAULT_FORECAST_DAYS."
        )

    if DEFAULT_SIMULATION_DAYS < 1:
        raise ValueError(
            "DEFAULT_SIMULATION_DAYS must be >= 1."
        )

    if MAX_SIMULATION_DAYS < DEFAULT_SIMULATION_DAYS:
        raise ValueError(
            "MAX_SIMULATION_DAYS must be >= DEFAULT_SIMULATION_DAYS."
        )


validate_config()


__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "ENVIRONMENT",
    "DEBUG",
    "DEFAULT_HOME_ID",
    "BASE_DIR",
    "UPLOAD_FOLDER",
    "DATABASE_URL",
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_POOL_MIN",
    "DB_POOL_MAX",
    "API_HOST",
    "API_PORT",
    "HOST",
    "PORT",
    "CORS_ORIGINS",
    "DEFAULT_READINGS_LIMIT",
    "MAX_READINGS_LIMIT",
    "DEFAULT_HISTORY_HOURS",
    "MAX_HISTORY_HOURS",
    "MAX_UPLOAD_MB",
    "MAX_UPLOAD_BYTES",
    "MAX_UPLOAD_ROWS",
    "SUPPORTED_UPLOAD_EXTENSIONS",
    "DEFAULT_FORECAST_DAYS",
    "MAX_FORECAST_DAYS",
    "DEFAULT_SIMULATION_DAYS",
    "MAX_SIMULATION_DAYS",
    "ENERGY_UNIT",
    "POWER_UNIT",
    "CURRENCY",
    "TIMEZONE",
    "NEGATIVE_ENERGY_ALLOWED",
    "FORECAST_PERIODS_PER_DAY",
    "PRICING_PLANS",
    "DEFAULT_PRICING_PLAN",
    "TELEMETRY_SCHEMA_VERSION",
    "TELEMETRY_REQUIRED_FIELDS",
    "TELEMETRY_OPTIONAL_FIELDS",
    "TELEMETRY_FIELDS",
    "TELEMETRY_SOURCE_MQTT",
    "TELEMETRY_SOURCE_CSV",
    "TELEMETRY_SOURCE_API",
    "TELEMETRY_SOURCE_SIMULATION",
    "TELEMETRY_SOURCES",
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_KEEPALIVE",
    "MQTT_TOPIC",
    "MQTT_QOS",
    "MQTT_CLIENT_ID",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
    "MQTT_TLS_ENABLED",
    "MQTT_TLS_CA_CERT",
    "MQTT_STATUS_TOPIC",
    "EXPOSE_INTERNAL_ERRORS",
]