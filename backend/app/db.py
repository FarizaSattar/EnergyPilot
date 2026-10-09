from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_POOL_MAX,
    DB_POOL_MIN,
    DB_PORT,
    DB_USER,
)

from models import TelemetryReading


__all__ = [
    "get_pool",
    "get_connection",
    "init_db",
    "database_health",
    "insert_reading",
    "insert_readings",
    "get_readings",
    "latest_readings",
    "get_latest_reading",
    "count_readings",
    "get_stats",
    "get_database_stats",
    "readings_between",
    "hourly_summary",
    "daily_summary",
    "clear_readings",
    "delete_readings",
    "close_db",
]


# ============================================================================
# CONNECTION POOL
# ============================================================================

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """
    Return the shared PostgreSQL connection pool.
    """
    global _pool

    if _pool is None:
        _pool = ConnectionPool(
            conninfo=(
                f"host={DB_HOST} "
                f"port={DB_PORT} "
                f"dbname={DB_NAME} "
                f"user={DB_USER} "
                f"password={DB_PASSWORD}"
            ),
            min_size=DB_POOL_MIN,
            max_size=DB_POOL_MAX,
            kwargs={
                "row_factory": dict_row,
            },
            open=True,
        )

    return _pool


@contextmanager
def get_connection() -> Iterator[Connection]:
    """
    Borrow a PostgreSQL connection from the shared pool.
    """
    pool = get_pool()

    with pool.connection() as conn:
        yield conn


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_db() -> None:
    """
    Create the telemetry table and indexes if they do not exist.
    """

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS telemetry_readings (
                    id BIGSERIAL PRIMARY KEY,

                    building_id VARCHAR(128) NOT NULL,

                    timestamp TIMESTAMPTZ NOT NULL,

                    demand_kw DOUBLE PRECISION NOT NULL,

                    energy_kwh DOUBLE PRECISION NOT NULL,

                    temperature_c DOUBLE PRECISION,

                    occupancy INTEGER,

                    hvac_kw DOUBLE PRECISION,

                    lighting_kw DOUBLE PRECISION,

                    source VARCHAR(32) NOT NULL DEFAULT 'mqtt',

                    schema_version VARCHAR(16) NOT NULL DEFAULT '1.0',

                    created_at TIMESTAMPTZ NOT NULL
                        DEFAULT CURRENT_TIMESTAMP,

                    CONSTRAINT telemetry_demand_nonnegative
                        CHECK (demand_kw >= 0),

                    CONSTRAINT telemetry_energy_nonnegative
                        CHECK (energy_kwh >= 0),

                    CONSTRAINT telemetry_occupancy_nonnegative
                        CHECK (
                            occupancy IS NULL
                            OR occupancy >= 0
                        ),

                    CONSTRAINT telemetry_hvac_nonnegative
                        CHECK (
                            hvac_kw IS NULL
                            OR hvac_kw >= 0
                        ),

                    CONSTRAINT telemetry_lighting_nonnegative
                        CHECK (
                            lighting_kw IS NULL
                            OR lighting_kw >= 0
                        )
                );
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_telemetry_building_timestamp
                ON telemetry_readings (
                    building_id,
                    timestamp DESC
                );
                """
            )

            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_telemetry_timestamp
                ON telemetry_readings (
                    timestamp DESC
                );
                """
            )

        conn.commit()


# ============================================================================
# DATABASE HEALTH
# ============================================================================

def database_health() -> dict[str, Any]:
    """
    Check whether PostgreSQL is reachable.
    """

    try:
        started_at = datetime.now(timezone.utc)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok;")
                row = cur.fetchone()

        finished_at = datetime.now(timezone.utc)

        latency_ms = (
            finished_at - started_at
        ).total_seconds() * 1000.0

        if row and int(row["ok"]) == 1:
            return {
                "status": "healthy",
                "connected": True,
                "database": DB_NAME,
                "host": DB_HOST,
                "port": DB_PORT,
                "latency_ms": round(
                    latency_ms,
                    2,
                ),
            }

        return {
            "status": "unhealthy",
            "connected": False,
            "database": DB_NAME,
            "host": DB_HOST,
            "port": DB_PORT,
        }

    except Exception as exc:
        return {
            "status": "unhealthy",
            "connected": False,
            "database": DB_NAME,
            "host": DB_HOST,
            "port": DB_PORT,
            "error": str(exc),
        }


# ============================================================================
# HELPERS
# ============================================================================

def _timestamp_to_datetime(
    timestamp: str | datetime,
) -> datetime:
    """
    Convert an ISO-8601 timestamp or datetime into UTC-aware datetime.
    """

    if isinstance(timestamp, datetime):
        dt = timestamp

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(timezone.utc)

    value = str(timestamp).strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt.astimezone(timezone.utc)


def _serialize_database_row(
    row: dict[str, Any],
) -> dict[str, Any]:
    """
    Convert PostgreSQL values into API-compatible values.

    The API historically used:
        ts
        home_id
        building_id

    PostgreSQL uses:
        timestamp
        building_id
    """

    result = dict(row)

    # ------------------------------------------------------------------
    # Timestamp
    # ------------------------------------------------------------------

    timestamp = result.get("timestamp")

    if isinstance(timestamp, datetime):
        timestamp_iso = (
            timestamp
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

        result["timestamp"] = timestamp_iso
        result["ts"] = timestamp_iso

    # ------------------------------------------------------------------
    # Created timestamp
    # ------------------------------------------------------------------

    created_at = result.get("created_at")

    if isinstance(created_at, datetime):
        result["created_at"] = (
            created_at
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    # ------------------------------------------------------------------
    # IDs
    # ------------------------------------------------------------------

    if result.get("id") is not None:
        result["id"] = int(result["id"])

    if result.get("building_id") is not None:
        result["home_id"] = result["building_id"]

    # ------------------------------------------------------------------
    # Compatibility fields
    # ------------------------------------------------------------------

    source = result.get("source")

    result["is_simulated"] = (
        source in {
            "csv",
            "simulator",
            "simulation",
        }
    )

    return result


def _serialize_summary_timestamp(
    value: Any,
) -> Any:
    """
    Convert summary timestamps to canonical UTC ISO-8601.
    """

    if isinstance(value, datetime):
        return (
            value
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    return value


# ============================================================================
# INSERT ONE READING
# ============================================================================

def insert_reading(
    reading: TelemetryReading | dict[str, Any],
    source: str = "mqtt",
) -> dict[str, Any]:
    """
    Insert one canonical telemetry reading.
    """

    if isinstance(reading, dict):

        # --------------------------------------------------------------
        # Normalize API/CSV naming
        # --------------------------------------------------------------

        reading = dict(reading)

        if "timestamp" not in reading:
            if "ts" in reading:
                timestamp = reading["ts"]

                if isinstance(timestamp, datetime):
                    reading["timestamp"] = (
                        timestamp.isoformat()
                    )
                else:
                    reading["timestamp"] = str(
                        timestamp
                    )

        if "building_id" not in reading:
            reading["building_id"] = reading.get(
                "home_id"
            )

        # Allow caller-provided source
        source = reading.get(
            "source",
            source,
        )

        reading = TelemetryReading.from_dict(
            reading
        )

    if not isinstance(
        reading,
        TelemetryReading,
    ):
        raise TypeError(
            "reading must be a TelemetryReading "
            "or telemetry dictionary."
        )

    timestamp = _timestamp_to_datetime(
        reading.timestamp
    )

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO telemetry_readings (
                    building_id,
                    timestamp,
                    demand_kw,
                    energy_kwh,
                    temperature_c,
                    occupancy,
                    hvac_kw,
                    lighting_kw,
                    source,
                    schema_version
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                RETURNING
                    id,
                    building_id,
                    timestamp,
                    demand_kw,
                    energy_kwh,
                    temperature_c,
                    occupancy,
                    hvac_kw,
                    lighting_kw,
                    source,
                    schema_version,
                    created_at;
                """,
                (
                    reading.building_id,
                    timestamp,
                    reading.demand_kw,
                    reading.energy_kwh,
                    reading.temperature_c,
                    reading.occupancy,
                    reading.hvac_kw,
                    reading.lighting_kw,
                    source,
                    "1.0",
                ),
            )

            row = cur.fetchone()

        conn.commit()

    return _serialize_database_row(row)


# ============================================================================
# INSERT MANY READINGS
# ============================================================================

def insert_readings(
    readings: list[TelemetryReading | dict[str, Any]],
    source: str = "mqtt",
) -> int:
    """
    Insert multiple telemetry readings.

    Returns the number of successfully inserted records.
    """

    inserted = 0

    for reading in readings:

        reading_source = source

        if isinstance(reading, dict):
            reading_source = reading.get(
                "source",
                source,
            )

        insert_reading(
            reading,
            source=reading_source,
        )

        inserted += 1

    return inserted


# ============================================================================
# GET READINGS
# ============================================================================

def get_readings(
    building_id: str | None = None,
    limit: int = 500,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve telemetry readings.

    Results are newest first.
    """

    limit = max(
        1,
        min(
            int(limit),
            5000,
        ),
    )

    conditions: list[str] = []
    params: list[Any] = []

    if building_id:
        conditions.append(
            "building_id = %s"
        )

        params.append(
            building_id
        )

    if start_time is not None:

        if start_time.tzinfo is None:
            start_time = start_time.replace(
                tzinfo=timezone.utc
            )

        conditions.append(
            "timestamp >= %s"
        )

        params.append(
            start_time.astimezone(
                timezone.utc
            )
        )

    if end_time is not None:

        if end_time.tzinfo is None:
            end_time = end_time.replace(
                tzinfo=timezone.utc
            )

        conditions.append(
            "timestamp <= %s"
        )

        params.append(
            end_time.astimezone(
                timezone.utc
            )
        )

    where_clause = ""

    if conditions:
        where_clause = (
            "WHERE "
            + " AND ".join(conditions)
        )

    query = f"""
        SELECT
            id,
            building_id,
            timestamp,
            demand_kw,
            energy_kwh,
            temperature_c,
            occupancy,
            hvac_kw,
            lighting_kw,
            source,
            schema_version,
            created_at
        FROM telemetry_readings
        {where_clause}
        ORDER BY timestamp DESC
        LIMIT %s;
    """

    params.append(limit)

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                query,
                params,
            )

            rows = cur.fetchall()

    return [
        _serialize_database_row(row)
        for row in rows
    ]


# ============================================================================
# API COMPATIBILITY: LATEST READINGS
# ============================================================================

def latest_readings(
    building_id: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """
    Compatibility wrapper used by app.py.

    Returns newest readings first.
    """

    return get_readings(
        building_id=building_id,
        limit=limit,
    )


# ============================================================================
# API COMPATIBILITY: READINGS BETWEEN
# ============================================================================

def readings_between(
    building_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """
    Compatibility wrapper used by app.py.
    """

    # get_readings returns newest first.
    # app.py expects chronological order for analytics.

    rows = get_readings(
        building_id=building_id,
        limit=limit,
        start_time=start,
        end_time=end,
    )

    return list(
        reversed(rows)
    )


# ============================================================================
# LATEST READING
# ============================================================================

def get_latest_reading(
    building_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Return the newest telemetry reading.
    """

    rows = get_readings(
        building_id=building_id,
        limit=1,
    )

    if not rows:
        return None

    return rows[0]


# ============================================================================
# COUNT READINGS
# ============================================================================

def count_readings(
    building_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> int:
    """
    Count telemetry readings.
    """

    conditions: list[str] = []
    params: list[Any] = []

    if building_id:
        conditions.append(
            "building_id = %s"
        )
        params.append(
            building_id
        )

    if start_time is not None:

        if start_time.tzinfo is None:
            start_time = start_time.replace(
                tzinfo=timezone.utc
            )

        conditions.append(
            "timestamp >= %s"
        )

        params.append(
            start_time.astimezone(
                timezone.utc
            )
        )

    if end_time is not None:

        if end_time.tzinfo is None:
            end_time = end_time.replace(
                tzinfo=timezone.utc
            )

        conditions.append(
            "timestamp <= %s"
        )

        params.append(
            end_time.astimezone(
                timezone.utc
            )
        )

    where_clause = ""

    if conditions:
        where_clause = (
            "WHERE "
            + " AND ".join(conditions)
        )

    query = f"""
        SELECT COUNT(*) AS count
        FROM telemetry_readings
        {where_clause};
    """

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                query,
                params,
            )

            row = cur.fetchone()

    return int(
        row["count"]
    )


# ============================================================================
# STATISTICS
# ============================================================================

def get_stats(
    building_id: str | None = None,
) -> dict[str, Any]:
    """
    Return aggregate telemetry statistics.
    """

    if building_id:

        query = """
            SELECT
                COUNT(*) AS reading_count,

                COALESCE(
                    SUM(energy_kwh),
                    0
                ) AS total_energy_kwh,

                COALESCE(
                    AVG(demand_kw),
                    0
                ) AS average_demand_kw,

                COALESCE(
                    MAX(demand_kw),
                    0
                ) AS peak_demand_kw,

                MIN(timestamp) AS first_timestamp,

                MAX(timestamp) AS last_timestamp

            FROM telemetry_readings

            WHERE building_id = %s;
        """

        params = [
            building_id
        ]

    else:

        query = """
            SELECT
                COUNT(*) AS reading_count,

                COALESCE(
                    SUM(energy_kwh),
                    0
                ) AS total_energy_kwh,

                COALESCE(
                    AVG(demand_kw),
                    0
                ) AS average_demand_kw,

                COALESCE(
                    MAX(demand_kw),
                    0
                ) AS peak_demand_kw,

                MIN(timestamp) AS first_timestamp,

                MAX(timestamp) AS last_timestamp

            FROM telemetry_readings;
        """

        params = []

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                query,
                params,
            )

            row = cur.fetchone()

    result = dict(row)

    result["reading_count"] = int(
        result["reading_count"]
    )

    result["total_energy_kwh"] = float(
        result["total_energy_kwh"]
    )

    result["average_demand_kw"] = float(
        result["average_demand_kw"]
    )

    result["peak_demand_kw"] = float(
        result["peak_demand_kw"]
    )

    result["first_timestamp"] = (
        _serialize_summary_timestamp(
            result["first_timestamp"]
        )
    )

    result["last_timestamp"] = (
        _serialize_summary_timestamp(
            result["last_timestamp"]
        )
    )

    return result


# ============================================================================
# API COMPATIBILITY: DATABASE STATS
# ============================================================================

def get_database_stats() -> dict[str, Any]:
    """
    Compatibility wrapper used by app.py.

    Returns statistics for the entire database.
    """

    return get_stats()


# ============================================================================
# HOURLY SUMMARY
# ============================================================================

def hourly_summary(
    building_id: str | None = None,
    hours: int = 24,
) -> list[dict[str, Any]]:
    """
    Aggregate telemetry into hourly buckets.
    """

    hours = max(
        1,
        min(
            int(hours),
            744,
        ),
    )

    conditions = [
        """
        timestamp >=
        NOW() - (%s * INTERVAL '1 hour')
        """
    ]

    params: list[Any] = [
        hours
    ]

    if building_id:

        conditions.append(
            "building_id = %s"
        )

        params.append(
            building_id
        )

    where_clause = " AND ".join(
        conditions
    )

    query = f"""
        SELECT
            building_id,

            DATE_TRUNC(
                'hour',
                timestamp
            ) AS hour,

            COALESCE(
                SUM(energy_kwh),
                0
            ) AS energy_kwh,

            COALESCE(
                AVG(demand_kw),
                0
            ) AS average_demand_kw,

            COALESCE(
                MAX(demand_kw),
                0
            ) AS peak_demand_kw,

            AVG(
                temperature_c
            ) AS average_temperature_c,

            AVG(
                occupancy
            ) AS average_occupancy,

            COALESCE(
                AVG(hvac_kw),
                0
            ) AS average_hvac_kw,

            COALESCE(
                AVG(lighting_kw),
                0
            ) AS average_lighting_kw,

            COUNT(*) AS reading_count

        FROM telemetry_readings

        WHERE {where_clause}

        GROUP BY
            building_id,
            DATE_TRUNC(
                'hour',
                timestamp
            )

        ORDER BY hour ASC;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                query,
                params,
            )

            rows = cur.fetchall()

    results: list[dict[str, Any]] = []

    for row in rows:

        result = dict(row)

        result["hour"] = (
            _serialize_summary_timestamp(
                result["hour"]
            )
        )

        result["energy_kwh"] = float(
            result["energy_kwh"]
        )

        result["average_demand_kw"] = float(
            result["average_demand_kw"]
        )

        result["peak_demand_kw"] = float(
            result["peak_demand_kw"]
        )

        result["average_hvac_kw"] = float(
            result["average_hvac_kw"]
        )

        result["average_lighting_kw"] = float(
            result["average_lighting_kw"]
        )

        result["reading_count"] = int(
            result["reading_count"]
        )

        if result["average_temperature_c"] is not None:
            result["average_temperature_c"] = float(
                result["average_temperature_c"]
            )

        if result["average_occupancy"] is not None:
            result["average_occupancy"] = float(
                result["average_occupancy"]
            )

        results.append(result)

    return results


# ============================================================================
# DAILY SUMMARY
# ============================================================================

def daily_summary(
    building_id: str | None = None,
    days: int = 30,
) -> list[dict[str, Any]]:
    """
    Aggregate telemetry into daily buckets.
    """

    days = max(
        1,
        min(
            int(days),
            365,
        ),
    )

    conditions = [
        """
        timestamp >=
        NOW() - (%s * INTERVAL '1 day')
        """
    ]

    params: list[Any] = [
        days
    ]

    if building_id:

        conditions.append(
            "building_id = %s"
        )

        params.append(
            building_id
        )

    where_clause = " AND ".join(
        conditions
    )

    query = f"""
        SELECT
            building_id,

            DATE_TRUNC(
                'day',
                timestamp
            ) AS day,

            COALESCE(
                SUM(energy_kwh),
                0
            ) AS energy_kwh,

            COALESCE(
                AVG(demand_kw),
                0
            ) AS average_demand_kw,

            COALESCE(
                MAX(demand_kw),
                0
            ) AS peak_demand_kw,

            AVG(
                temperature_c
            ) AS average_temperature_c,

            AVG(
                occupancy
            ) AS average_occupancy,

            COALESCE(
                AVG(hvac_kw),
                0
            ) AS average_hvac_kw,

            COALESCE(
                AVG(lighting_kw),
                0
            ) AS average_lighting_kw,

            COUNT(*) AS reading_count

        FROM telemetry_readings

        WHERE {where_clause}

        GROUP BY
            building_id,
            DATE_TRUNC(
                'day',
                timestamp
            )

        ORDER BY day ASC;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:

            cur.execute(
                query,
                params,
            )

            rows = cur.fetchall()

    results: list[dict[str, Any]] = []

    for row in rows:

        result = dict(row)

        result["day"] = (
            _serialize_summary_timestamp(
                result["day"]
            )
        )

        result["energy_kwh"] = float(
            result["energy_kwh"]
        )

        result["average_demand_kw"] = float(
            result["average_demand_kw"]
        )

        result["peak_demand_kw"] = float(
            result["peak_demand_kw"]
        )

        result["average_hvac_kw"] = float(
            result["average_hvac_kw"]
        )

        result["average_lighting_kw"] = float(
            result["average_lighting_kw"]
        )

        result["reading_count"] = int(
            result["reading_count"]
        )

        if result["average_temperature_c"] is not None:
            result["average_temperature_c"] = float(
                result["average_temperature_c"]
            )

        if result["average_occupancy"] is not None:
            result["average_occupancy"] = float(
                result["average_occupancy"]
            )

        results.append(result)

    return results


# ============================================================================
# CLEAR READINGS
# ============================================================================

def clear_readings(
    building_id: str | None = None,
) -> int:
    """
    Delete telemetry readings.
    """

    with get_connection() as conn:
        with conn.cursor() as cur:

            if building_id:

                cur.execute(
                    """
                    DELETE FROM telemetry_readings
                    WHERE building_id = %s;
                    """,
                    (
                        building_id,
                    ),
                )

            else:

                cur.execute(
                    """
                    DELETE FROM telemetry_readings;
                    """
                )

            deleted_count = cur.rowcount

        conn.commit()

    return int(
        deleted_count
    )


# Backward-compatible alias.
delete_readings = clear_readings


# ============================================================================
# CLOSE DATABASE
# ============================================================================

def close_db() -> None:
    """
    Close the PostgreSQL connection pool.
    """

    global _pool

    if _pool is not None:
        _pool.close()
        _pool = None