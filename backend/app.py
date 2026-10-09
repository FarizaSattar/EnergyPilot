"""
EnergyPilot Flask API
=====================

Backend API for the EnergyPilot residential energy-monitoring platform.

Architecture:

    Physical EnergyPilot Device
                OR
    Smart-Meter Simulator
                |
                v
               MQTT
                |
                v
      mqtt_ingestor.py
                |
                v
          PostgreSQL
                |
                v
              app.py
                |
        +---+-------------------+
        |                       |
        v                       v
    Analytics             Pricing Engine
        |                       |
        +-----------+-----------+
                    |
                    v
              React Frontend

Important:
    app.py does NOT generate fake/demo meter readings.

    The simulator is treated as a hardware substitute. A future physical
    EnergyPilot device should publish the same telemetry schema over MQTT,
    allowing the backend to remain unchanged.

Database:
    PostgreSQL access is provided by app/db.py.

Pricing:
    analytics/pricing.py

Compatibility:
    "building_id" is retained in the database/API because the original
    EnergyPilot architecture used that field.

    For the residential system:

        building_id == home_id
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

from config import (
    API_HOST,
    API_PORT,
    CORS_ORIGINS,
    DEFAULT_HOME_ID,
    DEBUG,
)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

from app.db import (
    clear_readings,
    count_readings,
    daily_summary,
    database_health,
    get_database_stats,
    hourly_summary,
    insert_readings,
    latest_readings,
    readings_between,
)

# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

from analytics.pricing import (
    calculate_plan_costs,
    calculate_tou_breakdown,
    compare_plans,
    recommend_plan,
)

# ---------------------------------------------------------------------------
# Optional analytics modules
# ---------------------------------------------------------------------------

try:
    from analytics.analytics import analyze_readings
except (ImportError, AttributeError):
    analyze_readings = None


try:
    from analytics.forecasting import forecast_demand
except (ImportError, AttributeError):
    forecast_demand = None


try:
    from analytics.recommendations import generate_recommendations
except (ImportError, AttributeError):
    generate_recommendations = None


# ============================================================================
# Application
# ============================================================================

app = Flask(__name__)

app.config["JSON_SORT_KEYS"] = False

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": CORS_ORIGINS,
        }
    },
)


# ============================================================================
# Constants
# ============================================================================

APP_VERSION = "2.0.0"

MAX_READINGS_LIMIT = 5_000
DEFAULT_READINGS_LIMIT = 500

DEFAULT_HISTORY_HOURS = 24
MAX_HISTORY_HOURS = 24 * 31

SUPPORTED_UPLOAD_EXTENSIONS = {
    ".csv",
}


# ============================================================================
# JSON helpers
# ============================================================================

def _json_safe(value: Any) -> Any:
    """
    Recursively convert pandas/numpy/Python values into JSON-safe values.
    """
    if value is None:
        return None

    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            _json_safe(item)
            for item in value
        ]

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value

    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass

    return value


def _json_response(
    payload: Any,
    status: int = 200,
):
    """
    Return a JSON-safe Flask response.
    """
    return (
        jsonify(
            _json_safe(payload)
        ),
        status,
    )


def _error(
    message: str,
    status: int = 400,
    code: str = "BAD_REQUEST",
):
    """
    Standardized API error response.
    """
    return _json_response(
        {
            "error": {
                "code": code,
                "message": message,
            }
        },
        status,
    )


# ============================================================================
# Request helpers
# ============================================================================

def _get_home_id() -> str:
    """
    Get the requested home identifier.
    """
    home_id = (
        request.args.get("home_id")
        or request.args.get("building_id")
        or DEFAULT_HOME_ID
    )

    home_id = str(home_id).strip()

    if not home_id:
        return DEFAULT_HOME_ID

    return home_id


def _parse_limit(
    default: int = DEFAULT_READINGS_LIMIT,
) -> int:
    """
    Parse and constrain the requested reading limit.
    """
    raw_limit = request.args.get(
        "limit",
        default,
    )

    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "limit must be an integer."
        ) from exc

    if limit <= 0:
        raise ValueError(
            "limit must be greater than zero."
        )

    return min(
        limit,
        MAX_READINGS_LIMIT,
    )


def _parse_hours(
    default: int = DEFAULT_HISTORY_HOURS,
) -> int:
    """
    Parse a bounded history window.
    """
    raw_hours = request.args.get(
        "hours",
        default,
    )

    try:
        hours = int(raw_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "hours must be an integer."
        ) from exc

    if hours < 1:
        raise ValueError(
            "hours must be at least 1."
        )

    return min(
        hours,
        MAX_HISTORY_HOURS,
    )


def _parse_datetime(
    value: str | None,
    field_name: str,
) -> datetime | None:
    """
    Parse an ISO-8601 datetime.
    """
    if value is None or not str(value).strip():
        return None

    normalized = str(value).strip()

    if normalized.endswith("Z"):
        normalized = (
            normalized[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            normalized
        )
    except ValueError as exc:
        raise ValueError(
            f"{field_name} must be a valid ISO-8601 datetime."
        ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed


# ============================================================================
# Reading normalization
# ============================================================================

def _normalize_readings(
    readings: Any,
) -> list[dict[str, Any]]:
    """
    Convert database rows/DataFrames into JSON-friendly dictionaries.
    """
    if readings is None:
        return []

    if isinstance(
        readings,
        pd.DataFrame,
    ):
        if readings.empty:
            return []

        return [
            _json_safe(row)
            for row in readings.to_dict(
                orient="records"
            )
        ]

    if isinstance(
        readings,
        dict,
    ):
        return [
            _json_safe(readings)
        ]

    if isinstance(
        readings,
        (list, tuple),
    ):
        result: list[dict[str, Any]] = []

        for item in readings:
            if isinstance(
                item,
                dict,
            ):
                result.append(
                    _json_safe(item)
                )

            elif hasattr(
                item,
                "_asdict",
            ):
                result.append(
                    _json_safe(
                        item._asdict()
                    )
                )

            elif hasattr(
                item,
                "to_dict",
            ):
                result.append(
                    _json_safe(
                        item.to_dict()
                    )
                )

            else:
                result.append(
                    _json_safe(item)
                )

        return result

    if hasattr(
        readings,
        "to_dict",
    ):
        try:
            converted = readings.to_dict(
                orient="records"
            )

            return [
                _json_safe(item)
                for item in converted
            ]

        except TypeError:
            return [
                _json_safe(
                    readings.to_dict()
                )
            ]

    return []


def _readings_dataframe(
    readings: list[dict[str, Any]],
) -> pd.DataFrame:
    """
    Convert database/API readings into a DataFrame.
    """
    if not readings:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "energy_kwh",
                "demand_kw",
                "temperature_c",
                "occupancy",
                "hvac_kw",
                "lighting_kw",
            ]
        )

    df = pd.DataFrame(
        readings
    )

    if "timestamp" not in df.columns:
        if "ts" in df.columns:
            df["timestamp"] = df["ts"]
        else:
            df["timestamp"] = pd.NaT

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce",
        utc=True,
    )

    numeric_columns = [
        "energy_kwh",
        "demand_kw",
        "temperature_c",
        "occupancy",
        "hvac_kw",
        "lighting_kw",
        "voltage_v",
        "current_a",
        "power_factor",
        "frequency_hz",
        "cumulative_energy_kwh",
    ]

    for column in numeric_columns:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            )

    return df


# ============================================================================
# Database reading helpers
# ============================================================================

def _get_recent_readings(
    home_id: str,
    hours: int = DEFAULT_HISTORY_HOURS,
) -> list[dict[str, Any]]:
    """
    Retrieve persisted readings for a recent time window.
    """
    hours = max(
        1,
        min(
            int(hours),
            MAX_HISTORY_HOURS,
        ),
    )

    end = datetime.now(
        timezone.utc
    )

    start = (
        end
        - timedelta(
            hours=hours
        )
    )

    readings = readings_between(
        building_id=home_id,
        start=start,
        end=end,
        limit=MAX_READINGS_LIMIT,
    )

    return _normalize_readings(
        readings
    )


def _extract_latest(
    readings: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Return the latest reading.
    """
    if not readings:
        return {}

    return readings[-1]


# ============================================================================
# Basic dashboard metrics
# ============================================================================

def _calculate_basic_metrics(
    readings: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Calculate reliable dashboard-level metrics directly from telemetry.
    """
    if not readings:
        return {
            "reading_count": 0,
            "total_energy_kwh": 0.0,
            "average_demand_kw": 0.0,
            "peak_demand_kw": 0.0,
            "latest_demand_kw": 0.0,
        }

    df = _readings_dataframe(
        readings
    )

    def numeric_sum(column: str) -> float:
        if column not in df.columns:
            return 0.0
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if values.empty:
            return 0.0
        return float(values.sum())

    def numeric_mean(column: str) -> float:
        if column not in df.columns:
            return 0.0
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if values.empty:
            return 0.0
        return float(values.mean())

    def numeric_max(column: str) -> float:
        if column not in df.columns:
            return 0.0
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if values.empty:
            return 0.0
        return float(values.max())

    latest = _extract_latest(readings)

    try:
        latest_demand = float(
            latest.get("demand_kw", 0.0)
        )
    except (TypeError, ValueError):
        latest_demand = 0.0

    return {
        "reading_count": len(readings),
        "total_energy_kwh": round(numeric_sum("energy_kwh"), 3),
        "average_demand_kw": round(numeric_mean("demand_kw"), 3),
        "peak_demand_kw": round(numeric_max("demand_kw"), 3),
        "latest_demand_kw": round(latest_demand, 3),
    }


# ============================================================================
# Hourly summary helper
# ============================================================================

def _hourly_summary_from_readings(
    readings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Build an hourly summary from persisted readings.
    """
    if not readings:
        return []

    df = _readings_dataframe(readings)

    if df.empty:
        return []

    df = df.dropna(subset=["timestamp"])

    if df.empty:
        return []

    if "energy_kwh" not in df.columns:
        df["energy_kwh"] = 0.0

    if "demand_kw" not in df.columns:
        df["demand_kw"] = 0.0

    df["energy_kwh"] = pd.to_numeric(df["energy_kwh"], errors="coerce").fillna(0.0)
    df["demand_kw"] = pd.to_numeric(df["demand_kw"], errors="coerce").fillna(0.0)

    df["hour"] = df["timestamp"].dt.floor("h")

    grouped = (
        df.groupby("hour", as_index=False)
        .agg(
            kwh=("energy_kwh", "sum"),
            average_kw=("demand_kw", "mean"),
            peak_kw=("demand_kw", "max"),
        )
        .sort_values("hour")
    )

    return [
        {
            "hour": row["hour"].isoformat(),
            "kwh": round(float(row["kwh"]), 3),
            "average_kw": round(float(row["average_kw"]), 3),
            "peak_kw": round(float(row["peak_kw"]), 3),
        }
        for _, row in grouped.iterrows()
    ]


# ============================================================================
# Root / service health
# ============================================================================

@app.get("/")
def index():
    """
    API information endpoint.
    """
    return _json_response(
        {
            "name": "EnergyPilot API",
            "version": APP_VERSION,
            "status": "online",
            "architecture": {
                "telemetry_source": "physical EnergyPilot device or smart-meter simulator",
                "transport": "MQTT",
                "storage": "PostgreSQL",
                "pricing": "analytics.pricing",
            },
            "endpoints": [
                "/health",
                "/api/dashboard",
                "/api/readings",
                "/api/analytics",
                "/api/pricing",
                "/api/pricing/analysis",
                "/api/recommendations",
                "/api/forecast",
                "/api/stats",
                "/api/summary/hourly",
                "/api/summary/daily",
                "/api/simulation",
                "/api/upload-csv",
            ],
        }
    )


@app.get("/health")
def health():
    """
    Detailed API/database health.
    """
    try:
        db_status = database_health()

        healthy = (
            isinstance(db_status, dict)
            and db_status.get("status") == "healthy"
        )

        return _json_response(
            {
                "status": "healthy" if healthy else "degraded",
                "service": "energypilot-api",
                "database": db_status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            200 if healthy else 503,
        )

    except Exception as exc:
        app.logger.exception("Health check failed.")
        return _error(
            f"Health check failed: {exc}",
            503,
            "HEALTH_CHECK_FAILED",
        )


# ============================================================================
# Dashboard
# ============================================================================

@app.get("/api/dashboard")
def dashboard():
    """
    Return the primary EnergyPilot dashboard payload.
    """
    try:
        home_id = _get_home_id()

        readings = _get_recent_readings(
            home_id=home_id,
            hours=DEFAULT_HISTORY_HOURS,
        )

        latest = _extract_latest(readings)
        metrics = _calculate_basic_metrics(readings)
        pricing = calculate_plan_costs(readings)
        recommendation = recommend_plan(readings)

        return _json_response(
            {
                "home_id": home_id,
                "building_id": home_id,
                "metrics": metrics,
                "latest": latest,
                "pricing": pricing,
                "recommended_plan": recommendation,
                "readings": readings[-100:],
                "data_source": latest.get("source", "unknown") if latest else None,
                "is_simulated": latest.get("is_simulated") if latest else None,
                "last_updated": latest.get("ts") if latest else None,
            }
        )

    except Exception as exc:
        app.logger.exception("Dashboard request failed.")
        return _error(
            f"Unable to load dashboard data: {exc}",
            500,
            "DASHBOARD_FAILED",
        )


# ============================================================================
# Readings
# ============================================================================

@app.get("/api/readings")
def readings():
    """
    Return historical smart-meter readings.
    """
    try:
        home_id = _get_home_id()
        limit = _parse_limit()

        start = _parse_datetime(request.args.get("start"), "start")
        end = _parse_datetime(request.args.get("end"), "end")

        if start is not None and end is not None and start > end:
            return _error(
                "start must be earlier than end.",
                400,
                "INVALID_DATE_RANGE",
            )

        if start is not None or end is not None:
            rows = readings_between(
                building_id=home_id,
                start=start,
                end=end,
                limit=limit,
            )
        else:
            rows = latest_readings(
                building_id=home_id,
                limit=limit,
            )

        normalized = _normalize_readings(rows)

        return _json_response(
            {
                "home_id": home_id,
                "building_id": home_id,
                "count": len(normalized),
                "readings": normalized,
            }
        )

    except ValueError as exc:
        return _error(str(exc), 400, "INVALID_REQUEST")

    except Exception as exc:
        app.logger.exception("Reading request failed.")
        return _error(
            f"Unable to load readings: {exc}",
            500,
            "READINGS_FAILED",
        )


# ============================================================================
# Analytics
# ============================================================================

@app.get("/api/analytics")
def analytics():
    """
    Return load analytics.
    """
    try:
        home_id = _get_home_id()
        hours = _parse_hours()

        readings_data = _get_recent_readings(
            home_id=home_id,
            hours=hours,
        )

        df = _readings_dataframe(readings_data)

        result: dict[str, Any] = {
            "home_id": home_id,
            "building_id": home_id,
            "period_hours": hours,
            "metrics": _calculate_basic_metrics(readings_data),
            "reading_count": len(readings_data),
        }

        if analyze_readings is not None:
            try:
                result["analysis"] = _json_safe(analyze_readings(df))
            except TypeError:
                try:
                    result["analysis"] = _json_safe(analyze_readings(readings_data))
                except Exception as exc:
                    result["analysis"] = {
                        "status": "unavailable",
                        "error": str(exc),
                    }
            except Exception as exc:
                result["analysis"] = {
                    "status": "unavailable",
                    "error": str(exc),
                }
        else:
            result["analysis"] = {
                "status": "unavailable",
                "message": "analytics/analytics.py was not found or does not export analyze_readings().",
            }

        return _json_response(result)

    except ValueError as exc:
        return _error(str(exc), 400, "INVALID_ANALYTICS_REQUEST")

    except Exception as exc:
        app.logger.exception("Analytics request failed.")
        return _error(
            f"Unable to calculate analytics: {exc}",
            500,
            "ANALYTICS_FAILED",
        )


# ============================================================================
# Pricing
# ============================================================================

@app.get("/api/pricing")
def pricing():
    """
    Compare electricity pricing plans for the current consumption profile.
    """
    try:
        home_id = _get_home_id()
        hours = _parse_hours()

        readings_data = _get_recent_readings(
            home_id=home_id,
            hours=hours,
        )

        costs = calculate_plan_costs(readings_data)
        comparison = compare_plans(readings_data)
        recommendation = recommend_plan(readings_data)
        tou_breakdown = calculate_tou_breakdown(readings_data)

        return _json_response(
            {
                "home_id": home_id,
                "building_id": home_id,
                "currency": "CAD",
                "country": "CA",
                "region": "Canada",
                "province": "ON",
                "period_hours": hours,
                "plans": costs,
                "comparison": comparison,
                "recommendation": recommendation,
                "tou_breakdown": tou_breakdown,
                "reading_count": len(readings_data),
            }
        )

    except ValueError as exc:
        return _error(str(exc), 400, "INVALID_PRICING_REQUEST")

    except Exception as exc:
        app.logger.exception("Pricing request failed.")
        return _error(
            f"Unable to calculate pricing: {exc}",
            500,
            "PRICING_FAILED",
        )


@app.get("/api/pricing/analysis")
def pricing_analysis():
    """
    Detailed pricing analysis for the Savings Engine.
    """
    try:
        home_id = _get_home_id()
        hours = _parse_hours()

        readings_data = _get_recent_readings(
            home_id=home_id,
            hours=hours,
        )

        costs = calculate_plan_costs(readings_data)
        comparison = compare_plans(readings_data)
        recommendation = recommend_plan(readings_data)
        tou_breakdown = calculate_tou_breakdown(readings_data)

        return _json_response(
            {
                "home_id": home_id,
                "building_id": home_id,
                "period_hours": hours,
                "currency": "CAD",
                "plans": costs,
                "comparison": comparison,
                "recommendation": recommendation,
                "tou_breakdown": tou_breakdown,
                "reading_count": len(readings_data),
            }
        )

    except ValueError as exc:
        return _error(str(exc), 400, "INVALID_PRICING_ANALYSIS_REQUEST")

    except Exception as exc:
        app.logger.exception("Pricing analysis failed.")
        return _error(
            f"Unable to calculate pricing analysis: {exc}",
            500,
            "PRICING_ANALYSIS_FAILED",
        )


# ============================================================================
# Recommendations
# ============================================================================

@app.get("/api/recommendations")
def recommendations():
    """
    Generate energy-saving recommendations.

    The pricing recommendation is always available.
    The optional recommendations module is used when present.
    """
    try:
        home_id = _get_home_id()
        hours = _parse_hours()

        readings_data = _get_recent_readings(
            home_id=home_id,
            hours=hours,
        )

        df = _readings_dataframe(readings_data)
        pricing_result = recommend_plan(readings_data)

        result: dict[str, Any] = {
            "home_id": home_id,
            "building_id": home_id,
            "period_hours": hours,
            "pricing": pricing_result,
            "recommendations": [],
        }

        if generate_recommendations is not None:
            try:
                generated = generate_recommendations(df)
            except TypeError:
                generated = generate_recommendations(readings_data)

            result["recommendations"] = _json_safe(generated)
        else:
            result["recommendations"] = [
                {
                    "type": "pricing",
                    "title": "Electricity plan recommendation",
                    "message": (
                        "EnergyPilot recommends the "
                        f"{pricing_result.get('recommended_plan', 'unknown')} "
                        "plan based on the supplied consumption profile."
                    ),
                    "recommended_plan": pricing_result.get("recommended_plan"),
                    "estimated_savings": pricing_result.get(
                        "estimated_savings",
                        0.0,
                    ),
                }
            ]

        return _json_response(result)

    except ValueError as exc:
        return _error(
            str(exc),
            400,
            "INVALID_RECOMMENDATION_REQUEST",
        )

    except Exception as exc:
        app.logger.exception("Recommendation request failed.")
        return _error(
            f"Unable to generate recommendations: {exc}",
            500,
            "RECOMMENDATIONS_FAILED",
        )


# ============================================================================
# Forecast
# ============================================================================

@app.get("/api/forecast")
def forecast():
    """
    Return demand forecast data.

    Forecasting remains optional so the core EnergyPilot API does not depend
    on an ML model being installed.
    """
    try:
        home_id = _get_home_id()

        readings_data = _get_recent_readings(
            home_id=home_id,
            hours=24 * 7,
        )

        df = _readings_dataframe(readings_data)

        if forecast_demand is None:
            return _json_response(
                {
                    "home_id": home_id,
                    "status": "unavailable",
                    "message": (
                        "analytics/forecasting.py was not found "
                        "or does not export forecast_demand()."
                    ),
                    "forecast": [],
                }
            )

        try:
            forecast_result = forecast_demand(df)
        except TypeError:
            forecast_result = forecast_demand(readings_data)

        return _json_response(
            {
                "home_id": home_id,
                "status": "available",
                "forecast": _json_safe(forecast_result),
            }
        )

    except Exception as exc:
        app.logger.exception("Forecast request failed.")
        return _error(
            f"Unable to generate forecast: {exc}",
            500,
            "FORECAST_FAILED",
        )


# ============================================================================
# Statistics
# ============================================================================

@app.get("/api/stats")
def stats():
    """
    Return database/system statistics.
    """
    try:
        home_id = _get_home_id()

        database_stats = get_database_stats()
        home_reading_count = count_readings(
            building_id=home_id
        )

        return _json_response(
            {
                "home_id": home_id,
                "building_id": home_id,
                "database": database_stats,
                "home_readings": home_reading_count,
            }
        )

    except Exception as exc:
        app.logger.exception("Stats request failed.")
        return _error(
            f"Unable to load statistics: {exc}",
            500,
            "STATS_FAILED",
        )


# ============================================================================
# Hourly summary
# ============================================================================

@app.get("/api/summary/hourly")
def summary_hourly():
    """
    Return hourly energy/demand summary for a selected history window.

    IMPORTANT:
        The current db.py hourly_summary() does not accept start/end.
        Therefore this endpoint retrieves the requested window and performs
        the final hourly aggregation in Python.
    """
    try:
        home_id = _get_home_id()
        hours = _parse_hours()

        readings_data = _get_recent_readings(
            home_id=home_id,
            hours=hours,
        )

        summary = _hourly_summary_from_readings(readings_data)

        return _json_response(
            {
                "home_id": home_id,
                "building_id": home_id,
                "hours": hours,
                "summary": summary,
            }
        )

    except ValueError as exc:
        return _error(
            str(exc),
            400,
            "INVALID_HOURS",
        )

    except Exception as exc:
        app.logger.exception("Hourly summary failed.")
        return _error(
            f"Unable to load hourly summary: {exc}",
            500,
            "HOURLY_SUMMARY_FAILED",
        )


# ============================================================================
# Daily summary
# ============================================================================

@app.get("/api/summary/daily")
def summary_daily():
    """
    Return persisted daily energy summary.
    """
    try:
        home_id = _get_home_id()

        result = daily_summary(
            building_id=home_id
        )

        return _json_response(
            {
                "home_id": home_id,
                "building_id": home_id,
                "summary": _normalize_readings(result),
            }
        )

    except Exception as exc:
        app.logger.exception("Daily summary failed.")
        return _error(
            f"Unable to load daily summary: {exc}",
            500,
            "DAILY_SUMMARY_FAILED",
        )


# ============================================================================
# Simulation / telemetry status
# ============================================================================

@app.get("/api/simulation")
def simulation():
    """
    Return current telemetry/simulator status.

    This endpoint does NOT generate readings.
    """
    try:
        home_id = _get_home_id()

        rows = latest_readings(
            building_id=home_id,
            limit=1,
        )

        latest = _extract_latest(
            _normalize_readings(
                rows
            )
        )

        telemetry = (
            latest.get(
                "telemetry"
            )
            if latest
            else None
        )

        if not isinstance(
            telemetry,
            dict,
        ):
            telemetry = {}

        return _json_response(
            {
                "home_id": home_id,
                "building_id": home_id,
                "latest_reading": latest,
                "data_source": (
                    telemetry.get(
                        "source"
                    )
                    if telemetry
                    else None
                ),
                "is_simulated": (
                    telemetry.get(
                        "is_simulated"
                    )
                    if telemetry
                    else None
                ),
                "device_id": (
                    telemetry.get(
                        "device_id"
                    )
                    if telemetry
                    else None
                ),
                "schema_version": (
                    telemetry.get(
                        "schema_version"
                    )
                    if telemetry
                    else None
                ),
                "quality": (
                    telemetry.get(
                        "quality"
                    )
                    if telemetry
                    else None
                ),
                "status": (
                    "receiving_data"
                    if latest
                    else "waiting_for_data"
                ),
                "message": (
                    "Telemetry is supplied by the "
                    "smart-meter simulator or future "
                    "physical EnergyPilot hardware."
                ),
            }
        )

    except Exception as exc:
        app.logger.exception(
            "Simulation status request failed."
        )

        return _error(
            f"Unable to load telemetry status: {exc}",
            500,
            "SIMULATION_STATUS_FAILED",
        )


# ============================================================================
# CSV upload
# ============================================================================

@app.post("/api/upload-csv")
def upload_csv():
    """
    Import historical meter data from a CSV file.

    Required CSV columns:

        timestamp
        energy_kwh

    Optional:

        demand_kw
        temperature_c
        occupancy
        hvac_kw
        lighting_kw
        voltage_v
        current_a
        power_factor
        frequency_hz
        cumulative_energy_kwh
    """
    try:
        if "file" not in request.files:
            return _error(
                "No CSV file was provided.",
                400,
                "FILE_REQUIRED",
            )

        uploaded_file = request.files[
            "file"
        ]

        filename = (
            uploaded_file.filename
            or ""
        ).strip()

        if not filename:
            return _error(
                "The uploaded file has no filename.",
                400,
                "INVALID_FILE",
            )

        extension = os.path.splitext(
            filename
        )[1].lower()

        if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
            return _error(
                "Only CSV files are supported.",
                400,
                "UNSUPPORTED_FILE",
            )

        home_id = _get_home_id()

        df = pd.read_csv(
            uploaded_file
        )

        if df.empty:
            return _error(
                "The CSV file is empty.",
                400,
                "EMPTY_FILE",
            )

        required_columns = {
            "timestamp",
            "energy_kwh",
        }

        missing = (
            required_columns
            - set(df.columns)
        )

        if missing:
            return _error(
                (
                    "CSV is missing required columns: "
                    + ", ".join(
                        sorted(missing)
                    )
                ),
                400,
                "MISSING_COLUMNS",
            )

        df["timestamp"] = pd.to_datetime(
            df["timestamp"],
            errors="coerce",
            utc=True,
        )

        df["energy_kwh"] = pd.to_numeric(
            df["energy_kwh"],
            errors="coerce",
        )

        invalid = df[
            df["timestamp"].isna()
            | df["energy_kwh"].isna()
            | (df["energy_kwh"] < 0)
        ]

        if not invalid.empty:
            return _error(
                (
                    f"CSV contains {len(invalid)} "
                    "invalid timestamp/energy rows."
                ),
                400,
                "INVALID_ROWS",
            )

        optional_numeric_columns = [
            "demand_kw",
            "temperature_c",
            "occupancy",
            "hvac_kw",
            "lighting_kw",
            "voltage_v",
            "current_a",
            "power_factor",
            "frequency_hz",
            "cumulative_energy_kwh",
        ]

        for column in optional_numeric_columns:
            if column in df.columns:
                df[column] = pd.to_numeric(
                    df[column],
                    errors="coerce",
                )

        records: list[dict[str, Any]] = []

        for row in df.to_dict(
            orient="records"
        ):
            energy_kwh = float(
                row["energy_kwh"]
            )

            reading: dict[str, Any] = {
                "building_id": home_id,
                "home_id": home_id,
                "ts": row[
                    "timestamp"
                ].to_pydatetime(),
                "energy_kwh": energy_kwh,
            }

            demand_value = row.get(
                "demand_kw"
            )

            if pd.notna(
                demand_value
            ):
                reading["demand_kw"] = float(
                    demand_value
                )
            else:
                reading["demand_kw"] = (
                    energy_kwh * 4.0
                )

            for column in (
                "temperature_c",
                "occupancy",
                "hvac_kw",
                "lighting_kw",
            ):
                value = row.get(
                    column
                )

                if pd.notna(value):
                    reading[column] = float(
                        value
                    )

            for column in (
                "voltage_v",
                "current_a",
                "power_factor",
                "frequency_hz",
                "cumulative_energy_kwh",
            ):
                value = row.get(
                    column
                )

                if pd.notna(value):
                    reading[column] = float(
                        value
                    )

            reading["source"] = "csv"
            reading["is_simulated"] = True
            reading["quality"] = "imported"
            reading["schema_version"] = "1.0"

            records.append(
                reading
            )

        inserted = insert_readings(
            records
        )

        return _json_response(
            {
                "home_id": home_id,
                "filename": filename,
                "rows_received": len(
                    records
                ),
                "rows_inserted": inserted,
                "source": "csv",
            },
            201,
        )

    except ValueError as exc:
        return _error(
            str(exc),
            400,
            "INVALID_CSV",
        )

    except Exception as exc:
        app.logger.exception(
            "CSV upload failed."
        )

        return _error(
            f"Unable to import CSV: {exc}",
            500,
            "CSV_UPLOAD_FAILED",
        )


# ============================================================================
# Delete readings
# ============================================================================

@app.delete("/api/readings")
def delete_readings():
    """
    Delete readings for one home.

    This is intentionally explicit because deleting telemetry is destructive.
    """
    try:
        home_id = _get_home_id()

        deleted = clear_readings(
            building_id=home_id
        )

        return _json_response(
            {
                "home_id": home_id,
                "deleted": deleted,
            }
        )

    except Exception as exc:
        app.logger.exception(
            "Reading deletion failed."
        )

        return _error(
            f"Unable to delete readings: {exc}",
            500,
            "DELETE_FAILED",
        )


# ============================================================================
# Error handlers
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return _error(
        "The requested endpoint does not exist.",
        404,
        "NOT_FOUND",
    )


@app.errorhandler(405)
def method_not_allowed(error):
    return _error(
        "The HTTP method is not supported for this endpoint.",
        405,
        "METHOD_NOT_ALLOWED",
    )


@app.errorhandler(413)
def request_entity_too_large(error):
    return _error(
        "The uploaded request is too large.",
        413,
        "REQUEST_TOO_LARGE",
    )


@app.errorhandler(500)
def internal_server_error(error):
    return _error(
        "An unexpected server error occurred.",
        500,
        "INTERNAL_SERVER_ERROR",
    )


# ============================================================================
# Application entry point
# ============================================================================

if __name__ == "__main__":
    app.run(
        host=API_HOST,
        port=API_PORT,
        debug=DEBUG,
    )