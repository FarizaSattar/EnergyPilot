"""
EnergyPilot domain models.

The TelemetryReading dataclass is the canonical representation of a
single EnergyPilot telemetry record.

Canonical telemetry contract
----------------------------

Required:
    building_id : str
    timestamp   : ISO-8601 UTC timestamp
    demand_kw   : float >= 0
    energy_kwh  : float >= 0

Optional:
    temperature_c : float | None
    occupancy     : int | None
    hvac_kw       : float | None
    lighting_kw   : float | None
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any


# ============================================================================
# Exceptions
# ============================================================================

class TelemetryValidationError(ValueError):
    """Raised when telemetry does not satisfy the canonical contract."""


# ============================================================================
# Validation helpers
# ============================================================================

def _require_string(
    value: Any,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise TelemetryValidationError(
            f"{field_name} must be a string."
        )

    value = value.strip()

    if not value:
        raise TelemetryValidationError(
            f"{field_name} cannot be empty."
        )

    return value


def _finite_float(
    value: Any,
    field_name: str,
    *,
    minimum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise TelemetryValidationError(
            f"{field_name} must be numeric."
        )

    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise TelemetryValidationError(
            f"{field_name} must be numeric."
        ) from exc

    if not math.isfinite(converted):
        raise TelemetryValidationError(
            f"{field_name} must be finite."
        )

    if minimum is not None and converted < minimum:
        raise TelemetryValidationError(
            f"{field_name} must be >= {minimum}."
        )

    return converted


def _optional_float(
    value: Any,
    field_name: str,
    *,
    minimum: float | None = None,
) -> float | None:
    if value is None:
        return None

    return _finite_float(
        value,
        field_name,
        minimum=minimum,
    )


def _optional_non_negative_int(
    value: Any,
    field_name: str,
) -> int | None:
    if value is None:
        return None

    if isinstance(value, bool):
        raise TelemetryValidationError(
            f"{field_name} must be an integer."
        )

    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise TelemetryValidationError(
            f"{field_name} must be an integer."
        ) from exc

    if not math.isfinite(numeric):
        raise TelemetryValidationError(
            f"{field_name} must be finite."
        )

    if numeric < 0:
        raise TelemetryValidationError(
            f"{field_name} must be >= 0."
        )

    if not numeric.is_integer():
        raise TelemetryValidationError(
            f"{field_name} must be an integer."
        )

    return int(numeric)


def normalize_timestamp(value: Any) -> str:
    """
    Validate and normalize a timestamp to an ISO-8601 UTC string.

    Examples accepted:

        2026-10-07T18:00:00Z
        2026-10-07T18:00:00+00:00
        2026-10-07T14:00:00-04:00
    """

    if not isinstance(value, str):
        raise TelemetryValidationError(
            "timestamp must be a string."
        )

    raw = value.strip()

    if not raw:
        raise TelemetryValidationError(
            "timestamp cannot be empty."
        )

    normalized = raw.replace("Z", "+00:00")

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TelemetryValidationError(
            "timestamp must be a valid ISO-8601 timestamp."
        ) from exc

    if parsed.tzinfo is None:
        raise TelemetryValidationError(
            "timestamp must include timezone information."
        )

    parsed_utc = parsed.astimezone(timezone.utc)

    return parsed_utc.isoformat().replace(
        "+00:00",
        "Z",
    )


# ============================================================================
# Telemetry model
# ============================================================================

@dataclass(frozen=True, slots=True)
class TelemetryReading:
    """
    Canonical EnergyPilot telemetry record.

    This object is intentionally identical to the PostgreSQL telemetry
    schema and MQTT payload contract.
    """

    building_id: str
    timestamp: str
    demand_kw: float
    energy_kwh: float

    temperature_c: float | None = None
    occupancy: int | None = None
    hvac_kw: float | None = None
    lighting_kw: float | None = None

    def __post_init__(self) -> None:
        building_id = _require_string(
            self.building_id,
            "building_id",
        )

        timestamp = normalize_timestamp(
            self.timestamp,
        )

        demand_kw = _finite_float(
            self.demand_kw,
            "demand_kw",
            minimum=0.0,
        )

        energy_kwh = _finite_float(
            self.energy_kwh,
            "energy_kwh",
            minimum=0.0,
        )

        temperature_c = _optional_float(
            self.temperature_c,
            "temperature_c",
        )

        occupancy = _optional_non_negative_int(
            self.occupancy,
            "occupancy",
        )

        hvac_kw = _optional_float(
            self.hvac_kw,
            "hvac_kw",
            minimum=0.0,
        )

        lighting_kw = _optional_float(
            self.lighting_kw,
            "lighting_kw",
            minimum=0.0,
        )

        object.__setattr__(
            self,
            "building_id",
            building_id,
        )

        object.__setattr__(
            self,
            "timestamp",
            timestamp,
        )

        object.__setattr__(
            self,
            "demand_kw",
            demand_kw,
        )

        object.__setattr__(
            self,
            "energy_kwh",
            energy_kwh,
        )

        object.__setattr__(
            self,
            "temperature_c",
            temperature_c,
        )

        object.__setattr__(
            self,
            "occupancy",
            occupancy,
        )

        object.__setattr__(
            self,
            "hvac_kw",
            hvac_kw,
        )

        object.__setattr__(
            self,
            "lighting_kw",
            lighting_kw,
        )

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "TelemetryReading":
        if not isinstance(payload, dict):
            raise TelemetryValidationError(
                "Telemetry payload must be an object."
            )

        required_fields = (
            "building_id",
            "timestamp",
            "demand_kw",
            "energy_kwh",
        )

        missing = [
            field
            for field in required_fields
            if field not in payload
        ]

        if missing:
            raise TelemetryValidationError(
                "Missing required telemetry fields: "
                + ", ".join(missing)
            )

        return cls(
            building_id=payload["building_id"],
            timestamp=payload["timestamp"],
            demand_kw=payload["demand_kw"],
            energy_kwh=payload["energy_kwh"],
            temperature_c=payload.get("temperature_c"),
            occupancy=payload.get("occupancy"),
            hvac_kw=payload.get("hvac_kw"),
            lighting_kw=payload.get("lighting_kw"),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Return the exact telemetry payload shape.
        """

        return {
            "building_id": self.building_id,
            "timestamp": self.timestamp,
            "demand_kw": self.demand_kw,
            "energy_kwh": self.energy_kwh,
            "temperature_c": self.temperature_c,
            "occupancy": self.occupancy,
            "hvac_kw": self.hvac_kw,
            "lighting_kw": self.lighting_kw,
        }


# ============================================================================
# Forecast
# ============================================================================

@dataclass(frozen=True, slots=True)
class ForecastPoint:
    timestamp: str
    predicted_kwh: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "timestamp",
            normalize_timestamp(self.timestamp),
        )

        object.__setattr__(
            self,
            "predicted_kwh",
            _finite_float(
                self.predicted_kwh,
                "predicted_kwh",
                minimum=0.0,
            ),
        )


# ============================================================================
# Recommendations
# ============================================================================

VALID_RECOMMENDATION_CATEGORIES = {
    "hvac",
    "lighting",
    "behavior",
    "equipment",
    "tariff",
    "general",
}

VALID_RECOMMENDATION_PRIORITIES = {
    "low",
    "medium",
    "high",
}


@dataclass(frozen=True, slots=True)
class Recommendation:
    title: str
    category: str
    description: str
    estimated_savings: float
    priority: str

    def __post_init__(self) -> None:
        title = _require_string(
            self.title,
            "title",
        )

        category = _require_string(
            self.category,
            "category",
        ).lower()

        description = _require_string(
            self.description,
            "description",
        )

        priority = _require_string(
            self.priority,
            "priority",
        ).lower()

        if category not in VALID_RECOMMENDATION_CATEGORIES:
            raise TelemetryValidationError(
                f"Invalid recommendation category: {category}"
            )

        if priority not in VALID_RECOMMENDATION_PRIORITIES:
            raise TelemetryValidationError(
                f"Invalid recommendation priority: {priority}"
            )

        estimated_savings = _finite_float(
            self.estimated_savings,
            "estimated_savings",
            minimum=0.0,
        )

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "description", description)
        object.__setattr__(
            self,
            "estimated_savings",
            estimated_savings,
        )
        object.__setattr__(self, "priority", priority)


# ============================================================================
# Backward-compatible alias
# ============================================================================

EnergyReading = TelemetryReading


__all__ = [
    "TelemetryValidationError",
    "TelemetryReading",
    "EnergyReading",
    "ForecastPoint",
    "Recommendation",
    "normalize_timestamp",
]