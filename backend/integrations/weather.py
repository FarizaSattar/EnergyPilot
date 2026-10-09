"""
EnergyPilot weather service.

This module is responsible only for retrieving and normalizing weather data
from Open-Meteo.

Architecture:

    Open-Meteo
        |
        v
    weather.py
        |
        v
    normalized EnergyPilot weather data
        |
        +--> Flask /api/weather
        |
        +--> forecasting
        |
        +--> recommendations
        |
        v
    React WeatherCard

Important design boundary:
    This module retrieves weather facts. It must not calculate energy savings,
    electricity prices, HVAC recommendations, or other business decisions.

Open-Meteo documentation:
    https://open-meteo.com/en/docs

Open-Meteo is used here as an external weather-data provider. The application
should not assume that a successful HTTP response means every requested
weather field is present, so response data is validated before it is returned.
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests


# =============================================================================
# Configuration
# =============================================================================

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
)

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0

DEFAULT_FORECAST_DAYS = 7
MIN_FORECAST_DAYS = 1
MAX_FORECAST_DAYS = 16

DEFAULT_TIMEZONE = "America/Toronto"

DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_DELAY_SECONDS = 1.0

LOGGER = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================

class WeatherAPIError(Exception):
    """Base exception for weather-service failures."""


class WeatherConfigurationError(WeatherAPIError):
    """Raised when weather-service configuration is invalid."""


class WeatherRequestError(WeatherAPIError):
    """Raised when Open-Meteo cannot be reached or returns an HTTP error."""


class WeatherResponseError(WeatherAPIError):
    """Raised when Open-Meteo returns malformed or incomplete data."""


# =============================================================================
# Data structures
# =============================================================================

@dataclass(frozen=True)
class WeatherConfig:
    """
    Runtime configuration for the Open-Meteo integration.

    Keeping this in a dataclass makes the service easier to test without
    modifying global state or environment variables.
    """

    url: str = OPEN_METEO_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS


# =============================================================================
# Weather-code mapping
# =============================================================================

# WMO weather interpretation codes used by Open-Meteo.
#
# Keeping this mapping here means the frontend does not need to understand
# provider-specific numeric weather codes.
WEATHER_CODE_DESCRIPTIONS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


# =============================================================================
# Configuration helpers
# =============================================================================

def _env_float(
    name: str,
    default: float,
) -> float:
    """Read a positive floating-point environment variable."""
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        value = float(raw)
    except ValueError as exc:
        raise WeatherConfigurationError(
            f"{name} must be a valid number."
        ) from exc

    if not math.isfinite(value) or value <= 0:
        raise WeatherConfigurationError(
            f"{name} must be a positive finite number."
        )

    return value


def _env_int(
    name: str,
    default: int,
) -> int:
    """Read an integer environment variable."""
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        value = int(raw)
    except ValueError as exc:
        raise WeatherConfigurationError(
            f"{name} must be a valid integer."
        ) from exc

    return value


def load_config() -> WeatherConfig:
    """
    Load weather-service configuration from environment variables.

    Supported variables:

        OPEN_METEO_URL
        WEATHER_TIMEOUT_SECONDS
        WEATHER_CONNECT_TIMEOUT_SECONDS
        WEATHER_MAX_RETRIES
        WEATHER_RETRY_DELAY_SECONDS
    """
    url = os.getenv(
        "OPEN_METEO_URL",
        OPEN_METEO_URL,
    ).strip()

    if not url.startswith(("https://", "http://")):
        raise WeatherConfigurationError(
            "OPEN_METEO_URL must be an HTTP(S) URL."
        )

    timeout = _env_float(
        "WEATHER_TIMEOUT_SECONDS",
        DEFAULT_TIMEOUT_SECONDS,
    )

    connect_timeout = _env_float(
        "WEATHER_CONNECT_TIMEOUT_SECONDS",
        DEFAULT_CONNECT_TIMEOUT_SECONDS,
    )

    max_retries = _env_int(
        "WEATHER_MAX_RETRIES",
        DEFAULT_MAX_RETRIES,
    )

    retry_delay = _env_float(
        "WEATHER_RETRY_DELAY_SECONDS",
        DEFAULT_RETRY_DELAY_SECONDS,
    )

    if not 0 <= max_retries <= 5:
        raise WeatherConfigurationError(
            "WEATHER_MAX_RETRIES must be between 0 and 5."
        )

    return WeatherConfig(
        url=url,
        timeout_seconds=timeout,
        connect_timeout_seconds=connect_timeout,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay,
    )


# =============================================================================
# Validation helpers
# =============================================================================

def _validate_coordinate(
    value: float,
    *,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    """Validate a geographic coordinate."""
    if isinstance(value, bool):
        raise ValueError(
            f"{name} must be numeric."
        )

    try:
        coordinate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{name} must be numeric."
        ) from exc

    if not math.isfinite(coordinate):
        raise ValueError(
            f"{name} must be finite."
        )

    if not minimum <= coordinate <= maximum:
        raise ValueError(
            f"{name} must be between "
            f"{minimum} and {maximum}."
        )

    return coordinate


def _validate_forecast_days(
    forecast_days: int,
) -> int:
    """Validate and clamp the requested forecast horizon."""
    if isinstance(forecast_days, bool):
        raise ValueError(
            "forecast_days must be an integer."
        )

    try:
        days = int(forecast_days)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "forecast_days must be an integer."
        ) from exc

    if not MIN_FORECAST_DAYS <= days <= MAX_FORECAST_DAYS:
        raise ValueError(
            f"forecast_days must be between "
            f"{MIN_FORECAST_DAYS} and {MAX_FORECAST_DAYS}."
        )

    return days


def _validate_timezone(
    timezone: str,
) -> str:
    """
    Validate an IANA timezone.

    Open-Meteo accepts IANA timezone names. Validating locally catches
    configuration mistakes before making an external request.
    """
    if not isinstance(timezone, str):
        raise ValueError(
            "timezone must be a string."
        )

    normalized = timezone.strip()

    if not normalized:
        raise ValueError(
            "timezone cannot be empty."
        )

    try:
        ZoneInfo(normalized)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Unknown IANA timezone '{normalized}'."
        ) from exc

    return normalized


def _safe_number(
    value: Any,
) -> float | None:
    """Convert a provider value to a finite float or None."""
    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    return number


def _safe_integer(
    value: Any,
) -> int | None:
    """Convert a provider value to an integer when possible."""
    if value is None or isinstance(value, bool):
        return None

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    return number


# =============================================================================
# Provider helpers
# =============================================================================

def get_weather_description(
    weather_code: int | None,
) -> str:
    """Translate a WMO weather code into a human-readable description."""
    if weather_code is None:
        return "Unknown"

    return WEATHER_CODE_DESCRIPTIONS.get(
        weather_code,
        "Unknown",
    )


def _get_hourly_array(
    hourly: Mapping[str, Any],
    key: str,
    length: int,
) -> list[Any]:
    """
    Safely retrieve an hourly provider array.

    Missing fields are represented as None rather than causing an IndexError.
    If Open-Meteo returns a shorter array than the timestamp array, the result
    is padded so each output record remains structurally valid.
    """
    value = hourly.get(key)

    if not isinstance(value, list):
        return [None] * length

    if len(value) >= length:
        return value[:length]

    return value + [None] * (length - len(value))


def _validate_hourly_payload(
    data: Any,
) -> Mapping[str, Any]:
    """Validate the top-level Open-Meteo response structure."""
    if not isinstance(data, Mapping):
        raise WeatherResponseError(
            "Weather API returned an invalid response object."
        )

    hourly = data.get("hourly")

    if not isinstance(hourly, Mapping):
        raise WeatherResponseError(
            "Weather API returned no hourly data."
        )

    timestamps = hourly.get("time")

    if not isinstance(timestamps, list) or not timestamps:
        raise WeatherResponseError(
            "Weather API returned no hourly timestamps."
        )

    return hourly


# =============================================================================
# HTTP client
# =============================================================================

def _is_retryable_status(
    status_code: int,
) -> bool:
    """Return whether an HTTP status is likely transient."""
    return status_code == 429 or 500 <= status_code <= 599


def _request(
    config: WeatherConfig,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Request weather data with bounded retries.

    Only transient failures are retried. Authentication/configuration errors
    are not relevant to this public Open-Meteo endpoint and should not be
    hidden behind repeated requests.
    """
    timeout = (
        config.connect_timeout_seconds,
        config.timeout_seconds,
    )

    attempts = config.max_retries + 1

    for attempt in range(attempts):
        try:
            response = requests.get(
                config.url,
                params=params,
                timeout=timeout,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "EnergyPilot/1.0",
                },
            )

        except requests.Timeout as exc:
            if attempt >= config.max_retries:
                raise WeatherRequestError(
                    "Weather API request timed out."
                ) from exc

            LOGGER.warning(
                "Weather API request timed out; retrying "
                "(attempt %d/%d).",
                attempt + 1,
                attempts,
            )

            time.sleep(
                config.retry_delay_seconds * (2**attempt)
            )
            continue

        except requests.RequestException as exc:
            if attempt >= config.max_retries:
                raise WeatherRequestError(
                    "Weather API request failed."
                ) from exc

            LOGGER.warning(
                "Weather API request failed; retrying "
                "(attempt %d/%d): %s",
                attempt + 1,
                attempts,
                exc,
            )

            time.sleep(
                config.retry_delay_seconds * (2**attempt)
            )
            continue

        if (
            _is_retryable_status(response.status_code)
            and attempt < config.max_retries
        ):
            LOGGER.warning(
                "Weather API returned HTTP %d; retrying "
                "(attempt %d/%d).",
                response.status_code,
                attempt + 1,
                attempts,
            )

            time.sleep(
                config.retry_delay_seconds * (2**attempt)
            )
            continue

        if response.status_code >= 400:
            detail = response.text[:500].strip()

            raise WeatherRequestError(
                "Weather API returned HTTP "
                f"{response.status_code}"
                + (f": {detail}" if detail else ".")
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise WeatherResponseError(
                "Weather API returned invalid JSON."
            ) from exc

        if not isinstance(data, dict):
            raise WeatherResponseError(
                "Weather API response must be a JSON object."
            )

        return data

    raise WeatherRequestError(
        "Weather API request failed after all retry attempts."
    )


# =============================================================================
# Normalization
# =============================================================================

def _build_hourly_records(
    hourly: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """
    Convert Open-Meteo's column-oriented hourly response into EnergyPilot's
    row-oriented representation.
    """
    timestamps = hourly["time"]
    count = len(timestamps)

    fields = {
        "temperature_2m": _get_hourly_array(
            hourly,
            "temperature_2m",
            count,
        ),
        "apparent_temperature": _get_hourly_array(
            hourly,
            "apparent_temperature",
            count,
        ),
        "relative_humidity_2m": _get_hourly_array(
            hourly,
            "relative_humidity_2m",
            count,
        ),
        "precipitation": _get_hourly_array(
            hourly,
            "precipitation",
            count,
        ),
        "rain": _get_hourly_array(
            hourly,
            "rain",
            count,
        ),
        "snowfall": _get_hourly_array(
            hourly,
            "snowfall",
            count,
        ),
        "cloud_cover": _get_hourly_array(
            hourly,
            "cloud_cover",
            count,
        ),
        "wind_speed_10m": _get_hourly_array(
            hourly,
            "wind_speed_10m",
            count,
        ),
        "wind_direction_10m": _get_hourly_array(
            hourly,
            "wind_direction_10m",
            count,
        ),
        "weather_code": _get_hourly_array(
            hourly,
            "weather_code",
            count,
        ),
    }

    records: list[dict[str, Any]] = []

    for index, timestamp in enumerate(timestamps):
        if not isinstance(timestamp, str) or not timestamp.strip():
            # A missing timestamp means the record cannot be meaningfully
            # consumed by forecasting or the UI.
            continue

        weather_code = _safe_integer(
            fields["weather_code"][index]
        )

        records.append(
            {
                "timestamp": timestamp,
                "temperature_c": _safe_number(
                    fields["temperature_2m"][index]
                ),
                "apparent_temperature_c": _safe_number(
                    fields["apparent_temperature"][index]
                ),
                "humidity_percent": _safe_number(
                    fields["relative_humidity_2m"][index]
                ),
                "precipitation_mm": _safe_number(
                    fields["precipitation"][index]
                ),
                "rain_mm": _safe_number(
                    fields["rain"][index]
                ),
                "snowfall_cm": _safe_number(
                    fields["snowfall"][index]
                ),
                "cloud_cover_percent": _safe_number(
                    fields["cloud_cover"][index]
                ),
                "wind_speed_kmh": _safe_number(
                    fields["wind_speed_10m"][index]
                ),
                "wind_direction_deg": _safe_number(
                    fields["wind_direction_10m"][index]
                ),
                "weather_code": weather_code,
                "condition": get_weather_description(
                    weather_code
                ),
            }
        )

    if not records:
        raise WeatherResponseError(
            "Weather API returned no usable hourly records."
        )

    return records


def _normalize_current_conditions(
    data: Mapping[str, Any],
) -> dict[str, Any] | None:
    """
    Normalize Open-Meteo current conditions when available.

    Current conditions are optional so the service remains compatible with
    providers/configurations that return hourly forecasts only.
    """
    current = data.get("current")

    if not isinstance(current, Mapping):
        return None

    weather_code = _safe_integer(
        current.get("weather_code")
    )

    return {
        "timestamp": current.get("time"),
        "temperature_c": _safe_number(
            current.get("temperature_2m")
        ),
        "apparent_temperature_c": _safe_number(
            current.get("apparent_temperature")
        ),
        "humidity_percent": _safe_number(
            current.get("relative_humidity_2m")
        ),
        "wind_speed_kmh": _safe_number(
            current.get("wind_speed_10m")
        ),
        "wind_direction_deg": _safe_number(
            current.get("wind_direction_10m")
        ),
        "weather_code": weather_code,
        "condition": get_weather_description(
            weather_code
        ),
    }


# =============================================================================
# Public API
# =============================================================================

def get_weather_forecast(
    latitude: float,
    longitude: float,
    timezone: str = DEFAULT_TIMEZONE,
    forecast_days: int = DEFAULT_FORECAST_DAYS,
    *,
    config: WeatherConfig | None = None,
) -> dict[str, Any]:
    """
    Retrieve and normalize hourly weather data from Open-Meteo.

    Parameters
    ----------
    latitude:
        Geographic latitude, -90 to 90.

    longitude:
        Geographic longitude, -180 to 180.

    timezone:
        IANA timezone such as "America/Toronto".

    forecast_days:
        Forecast horizon from 1 to 16 days.

    config:
        Optional WeatherConfig, primarily useful for tests.

    Returns
    -------
    dict
        Stable EnergyPilot weather response.

    Raises
    ------
    WeatherAPIError
        If the external request or response is invalid.
    """
    latitude = _validate_coordinate(
        latitude,
        name="latitude",
        minimum=-90.0,
        maximum=90.0,
    )

    longitude = _validate_coordinate(
        longitude,
        name="longitude",
        minimum=-180.0,
        maximum=180.0,
    )

    timezone = _validate_timezone(timezone)

    forecast_days = _validate_forecast_days(
        forecast_days
    )

    if config is None:
        config = load_config()

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "forecast_days": forecast_days,

        # Keep all requested weather variables together so the downstream
        # application receives a consistent hourly record.
        "hourly": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "precipitation",
                "rain",
                "snowfall",
                "cloud_cover",
                "wind_speed_10m",
                "wind_direction_10m",
                "weather_code",
            ]
        ),

        # Current conditions are useful for the Dashboard WeatherCard while
        # hourly data remains available for forecasting/recommendations.
        "current": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "relative_humidity_2m",
                "weather_code",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
    }

    LOGGER.info(
        "Requesting weather forecast for %.4f, %.4f "
        "(%d days, %s).",
        latitude,
        longitude,
        forecast_days,
        timezone,
    )

    data = _request(
        config,
        params,
    )

    hourly = _validate_hourly_payload(
        data
    )

    records = _build_hourly_records(
        hourly
    )

    current = _normalize_current_conditions(
        data
    )

    return {
        "latitude": _safe_number(
            data.get("latitude")
        ) or latitude,

        "longitude": _safe_number(
            data.get("longitude")
        ) or longitude,

        "timezone": data.get(
            "timezone",
            timezone,
        ),

        "timezone_abbreviation": data.get(
            "timezone_abbreviation"
        ),

        "elevation_m": _safe_number(
            data.get("elevation")
        ),

        "current": current,

        "hourly": records,

        "forecast_days": forecast_days,

        "source": "Open-Meteo",
    }


def get_current_weather(
    latitude: float,
    longitude: float,
    timezone: str = DEFAULT_TIMEZONE,
    *,
    config: WeatherConfig | None = None,
) -> dict[str, Any] | None:
    """
    Convenience helper returning current conditions.

    Returns None if the provider does not include current conditions.
    """
    forecast = get_weather_forecast(
        latitude,
        longitude,
        timezone,
        forecast_days=1,
        config=config,
    )

    return forecast.get("current")


def get_weather_summary(
    weather: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Create a compact summary for EnergyPilot's dashboard/API.

    This function does not infer energy recommendations. It simply exposes
    useful weather fields already present in the provider response.
    """
    if not isinstance(weather, Mapping):
        raise TypeError(
            "weather must be a mapping."
        )

    current = weather.get("current")

    if not isinstance(current, Mapping):
        current = {}

    return {
        "location": weather.get("location"),
        "latitude": weather.get("latitude"),
        "longitude": weather.get("longitude"),
        "timezone": weather.get("timezone"),

        "temperature_c": current.get(
            "temperature_c"
        ),

        "feels_like_c": current.get(
            "apparent_temperature_c"
        ),

        "condition": current.get(
            "condition"
        ),

        "humidity_percent": current.get(
            "humidity_percent"
        ),

        "wind_speed_kmh": current.get(
            "wind_speed_kmh"
        ),

        "wind_direction_deg": current.get(
            "wind_direction_deg"
        ),

        "timestamp": current.get(
            "timestamp"
        ),

        "source": weather.get(
            "source",
            "Open-Meteo",
        ),
    }


# =============================================================================
# Public API
# =============================================================================

__all__ = [
    "DEFAULT_FORECAST_DAYS",
    "DEFAULT_TIMEZONE",
    "MAX_FORECAST_DAYS",
    "MIN_FORECAST_DAYS",
    "OPEN_METEO_URL",
    "WeatherAPIError",
    "WeatherConfig",
    "WeatherConfigurationError",
    "WeatherRequestError",
    "WeatherResponseError",
    "get_current_weather",
    "get_weather_description",
    "get_weather_forecast",
    "get_weather_summary",
    "load_config",
]