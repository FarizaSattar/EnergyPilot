-- =============================================================================
-- EnergyPilot - Microsoft SQL Server Schema
-- =============================================================================
--
-- Purpose:
--   Persistent storage for building energy telemetry and forecasts.
--
-- Architecture:
--
--   MQTT / Simulator / CSV
--             |
--             v
--           db.py
--             |
--             v
--       Microsoft SQL Server
--          /           \
--         v             v
--   meter_readings   forecasts
--
-- Design principles:
--   - Database constraints protect data integrity.
--   - DATETIMEOFFSET is used for timestamps.
--   - Building + timestamp identifies a telemetry observation conceptually,
--     but uniqueness is intentionally NOT enforced.
--   - Indexes follow the application's most common query patterns.
--   - Forecasts are stored separately from measured data.
--   - Business logic belongs in the Python application layer.
--
-- IMPORTANT:
--   This file is designed for Microsoft SQL Server / T-SQL.
--
-- PostgreSQL -> SQL Server mappings used here:
--
--   BIGSERIAL / GENERATED IDENTITY -> BIGINT IDENTITY(1,1)
--   TEXT                        -> NVARCHAR(...)
--   TIMESTAMPTZ                 -> DATETIMEOFFSET
--   DOUBLE PRECISION            -> FLOAT
--   INTEGER                     -> INT
--   NOW()                       -> SYSDATETIMEOFFSET()
--   CREATE TABLE IF NOT EXISTS  -> IF NOT EXISTS + CREATE TABLE
--   CREATE INDEX IF NOT EXISTS  -> sys.indexes check + CREATE INDEX
--   CREATE OR REPLACE VIEW      -> CREATE OR ALTER VIEW
--   DISTINCT ON                 -> ROW_NUMBER()
--
-- Recommended SQL Server timezone:
--   Eastern Standard Time
--
-- =============================================================================


-- =============================================================================
-- 01. METER READINGS
-- =============================================================================

IF OBJECT_ID(N'dbo.meter_readings', N'U') IS NULL
BEGIN

    CREATE TABLE dbo.meter_readings
    (
        id BIGINT IDENTITY(1,1) NOT NULL,

        -- Logical building identifier.
        building_id NVARCHAR(255) NOT NULL,

        -- Measurement timestamp.
        --
        -- DATETIMEOFFSET stores:
        --   - date
        --   - time
        --   - UTC offset
        --
        -- This is preferred over DATETIME2 for telemetry because the
        -- measurement retains its offset information.
        ts DATETIMEOFFSET NOT NULL,

        -- Instantaneous electrical demand in kW.
        demand_kw FLOAT NOT NULL,

        -- Energy consumed during the measurement interval in kWh.
        energy_kwh FLOAT NOT NULL,

        -- Optional environmental / building signals.
        temperature_c FLOAT NULL,
        occupancy INT NULL,
        hvac_kw FLOAT NULL,
        lighting_kw FLOAT NULL,

        -- Database insertion timestamp.
        created_at DATETIMEOFFSET NOT NULL
            CONSTRAINT df_meter_readings_created_at
            DEFAULT SYSDATETIMEOFFSET(),

        -- ---------------------------------------------------------------------
        -- Primary key
        -- ---------------------------------------------------------------------

        CONSTRAINT pk_meter_readings
            PRIMARY KEY CLUSTERED (id),

        -- ---------------------------------------------------------------------
        -- Data integrity constraints
        -- ---------------------------------------------------------------------

        CONSTRAINT chk_meter_building_id_not_blank
            CHECK (LEN(LTRIM(RTRIM(building_id))) > 0),

        CONSTRAINT chk_meter_building_id_length
            CHECK (LEN(building_id) <= 100),

        CONSTRAINT chk_meter_demand_non_negative
            CHECK (demand_kw >= 0),

        CONSTRAINT chk_meter_energy_non_negative
            CHECK (energy_kwh >= 0),

        CONSTRAINT chk_meter_temperature_range
            CHECK
            (
                temperature_c IS NULL
                OR temperature_c BETWEEN -60 AND 60
            ),

        CONSTRAINT chk_meter_occupancy_non_negative
            CHECK
            (
                occupancy IS NULL
                OR occupancy >= 0
            ),

        CONSTRAINT chk_meter_hvac_non_negative
            CHECK
            (
                hvac_kw IS NULL
                OR hvac_kw >= 0
            ),

        CONSTRAINT chk_meter_lighting_non_negative
            CHECK
            (
                lighting_kw IS NULL
                OR lighting_kw >= 0
            )
    );

END;
GO


-- =============================================================================
-- 02. METER READING INDEXES
-- =============================================================================
--
-- Primary access pattern:
--
--   WHERE building_id = ?
--   ORDER BY ts DESC
--
-- This supports:
--   - dashboard latest readings
--   - time-series retrieval
--   - building analytics
--

IF NOT EXISTS
(
    SELECT 1
    FROM sys.indexes
    WHERE name = N'idx_meter_readings_building_ts'
      AND object_id = OBJECT_ID(N'dbo.meter_readings')
)
BEGIN

    CREATE INDEX idx_meter_readings_building_ts
    ON dbo.meter_readings
    (
        building_id ASC,
        ts DESC
    );

END;
GO


-- Useful for time-range analytics across all buildings.

IF NOT EXISTS
(
    SELECT 1
    FROM sys.indexes
    WHERE name = N'idx_meter_readings_ts'
      AND object_id = OBJECT_ID(N'dbo.meter_readings')
)
BEGIN

    CREATE INDEX idx_meter_readings_ts
    ON dbo.meter_readings
    (
        ts DESC
    );

END;
GO


-- Useful for queries that identify peak-demand events.

IF NOT EXISTS
(
    SELECT 1
    FROM sys.indexes
    WHERE name = N'idx_meter_readings_building_demand'
      AND object_id = OBJECT_ID(N'dbo.meter_readings')
)
BEGIN

    CREATE INDEX idx_meter_readings_building_demand
    ON dbo.meter_readings
    (
        building_id ASC,
        demand_kw DESC
    );

END;
GO


-- Useful for filtering telemetry by source.

IF NOT EXISTS
(
    SELECT 1
    FROM sys.indexes
    WHERE name = N'idx_meter_readings_source'
      AND object_id = OBJECT_ID(N'dbo.meter_readings')
)
BEGIN

    CREATE INDEX idx_meter_readings_source
    ON dbo.meter_readings
    (
        source
    );

END;
GO