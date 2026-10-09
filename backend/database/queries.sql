/*
===============================================================================
EnergyPilot - Microsoft SQL Server Query Library
===============================================================================

Database: Microsoft SQL Server
Driver:   pyodbc

Schema:
    dbo.meter_readings

Important:
    ts is DATETIMEOFFSET.

For EnergyPilot, timestamps are grouped using the timestamp's stored
offset. The application should normalize timestamps to Eastern Time
before inserting them if local Ontario calendar-day reporting is required.

===============================================================================
*/


/*
===============================================================================
01. LATEST READINGS
===============================================================================
*/

SELECT TOP (@limit)
    id,
    building_id,
    ts,
    demand_kw,
    energy_kwh,
    temperature_c,
    occupancy,
    hvac_kw,
    lighting_kw,
    source
FROM dbo.meter_readings
WHERE building_id = @building_id
ORDER BY
    ts DESC,
    id DESC;


/*
===============================================================================
02. LATEST READINGS IN CHRONOLOGICAL ORDER
===============================================================================
*/

SELECT
    id,
    building_id,
    ts,
    demand_kw,
    energy_kwh,
    temperature_c,
    occupancy,
    hvac_kw,
    lighting_kw,
    source
FROM
(
    SELECT TOP (@limit)
        id,
        building_id,
        ts,
        demand_kw,
        energy_kwh,
        temperature_c,
        occupancy,
        hvac_kw,
        lighting_kw,
        source
    FROM dbo.meter_readings
    WHERE building_id = @building_id
    ORDER BY
        ts DESC,
        id DESC
) AS recent
ORDER BY
    ts ASC,
    id ASC;


/*
===============================================================================
03. DAILY ENERGY
===============================================================================

Because ts is DATETIMEOFFSET, CAST(ts AS date) extracts the calendar date
represented by the stored timestamp.

===============================================================================
*/

SELECT
    CAST(ts AS date) AS day,

    ROUND(
        SUM(energy_kwh),
        3
    ) AS total_kwh

FROM dbo.meter_readings

WHERE building_id = @building_id

GROUP BY
    CAST(ts AS date)

ORDER BY
    day ASC;


/*
===============================================================================
04. DAILY PEAK DEMAND
===============================================================================
*/

SELECT
    CAST(ts AS date) AS day,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw

FROM dbo.meter_readings

WHERE building_id = @building_id

GROUP BY
    CAST(ts AS date)

ORDER BY
    day ASC;


/*
===============================================================================
05. DAILY ENERGY + DEMAND SUMMARY
===============================================================================
*/

SELECT
    CAST(ts AS date) AS day,

    ROUND(
        SUM(energy_kwh),
        3
    ) AS total_kwh,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw,

    COUNT(*) AS reading_count

FROM dbo.meter_readings

WHERE building_id = @building_id

GROUP BY
    CAST(ts AS date)

ORDER BY
    day ASC;


/*
===============================================================================
06. OVERALL BUILDING SUMMARY
===============================================================================
*/

SELECT
    building_id,

    COUNT(*) AS reading_count,

    MIN(ts) AS first_reading,

    MAX(ts) AS last_reading,

    ROUND(
        SUM(energy_kwh),
        3
    ) AS total_kwh,

    ROUND(
        AVG(energy_kwh),
        4
    ) AS average_interval_kwh,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw,

    ROUND(
        AVG(temperature_c),
        2
    ) AS average_temperature_c,

    ROUND(
        AVG(CAST(occupancy AS FLOAT)),
        2
    ) AS average_occupancy

FROM dbo.meter_readings

WHERE building_id = @building_id

GROUP BY
    building_id;


/*
===============================================================================
07. DATE-RANGE SUMMARY
===============================================================================

@start_ts = inclusive
@end_ts   = exclusive
===============================================================================
*/

SELECT
    COUNT(*) AS reading_count,

    MIN(ts) AS first_reading,

    MAX(ts) AS last_reading,

    ROUND(
        SUM(energy_kwh),
        3
    ) AS total_kwh,

    ROUND(
        AVG(energy_kwh),
        4
    ) AS average_interval_kwh,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw

FROM dbo.meter_readings

WHERE building_id = @building_id
  AND ts >= @start_ts
  AND ts < @end_ts;


/*
===============================================================================
08. HOURLY LOAD PROFILE
===============================================================================
*/

SELECT
    DATEPART(
        HOUR,
        ts
    ) AS hour_of_day,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw,

    ROUND(
        AVG(energy_kwh),
        4
    ) AS average_interval_kwh,

    COUNT(*) AS reading_count

FROM dbo.meter_readings

WHERE building_id = @building_id

GROUP BY
    DATEPART(
        HOUR,
        ts
    )

ORDER BY
    hour_of_day ASC;


/*
===============================================================================
09. WEEKDAY VS WEEKEND LOAD PROFILE
===============================================================================

Monday    = 0
Tuesday   = 1
Wednesday = 2
Thursday  = 3
Friday    = 4
Saturday  = 5
Sunday    = 6
===============================================================================
*/

WITH localized AS
(
    SELECT
        ts,
        demand_kw,
        energy_kwh,

        CAST(
            ts AS date
        ) AS local_date,

        DATEPART(
            HOUR,
            ts
        ) AS hour_of_day

    FROM dbo.meter_readings

    WHERE building_id = @building_id
)

SELECT
    CASE
        WHEN DATEDIFF(
            DAY,
            '19000101',
            local_date
        ) % 7 IN (5, 6)
        THEN N'weekend'
        ELSE N'weekday'
    END AS day_type,

    hour_of_day,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw,

    ROUND(
        AVG(energy_kwh),
        4
    ) AS average_interval_kwh,

    COUNT(*) AS reading_count

FROM localized

GROUP BY
    CASE
        WHEN DATEDIFF(
            DAY,
            '19000101',
            local_date
        ) % 7 IN (5, 6)
        THEN N'weekend'
        ELSE N'weekday'
    END,

    hour_of_day

ORDER BY
    day_type,
    hour_of_day;


/*
===============================================================================
10. DAILY END-USE ENERGY ESTIMATE
===============================================================================

Energy = kW x hours

The current reading's HVAC and lighting power is assumed to apply until
the next reading.

===============================================================================
*/

WITH readings AS
(
    SELECT
        id,
        ts,
        hvac_kw,
        lighting_kw,

        LEAD(ts) OVER
        (
            ORDER BY
                ts,
                id
        ) AS next_ts

    FROM dbo.meter_readings

    WHERE building_id = @building_id
),

intervals AS
(
    SELECT
        CAST(
            ts AS date
        ) AS day,

        hvac_kw,
        lighting_kw,

        DATEDIFF(
            SECOND,
            ts,
            next_ts
        ) / 3600.0 AS interval_hours

    FROM readings

    WHERE next_ts IS NOT NULL
)

SELECT
    day,

    ROUND(
        SUM(
            CASE
                WHEN interval_hours > 0
                 AND interval_hours <= @max_interval_hours
                THEN COALESCE(hvac_kw, 0) * interval_hours
                ELSE 0
            END
        ),
        3
    ) AS hvac_kwh,

    ROUND(
        SUM(
            CASE
                WHEN interval_hours > 0
                 AND interval_hours <= @max_interval_hours
                THEN COALESCE(lighting_kw, 0) * interval_hours
                ELSE 0
            END
        ),
        3
    ) AS lighting_kwh

FROM intervals

GROUP BY
    day

ORDER BY
    day ASC;


/*
===============================================================================
11. TEMPERATURE VS ENERGY
===============================================================================
*/

SELECT
    CAST(ts AS date) AS day,

    ROUND(
        AVG(temperature_c),
        2
    ) AS average_temperature_c,

    ROUND(
        SUM(energy_kwh),
        3
    ) AS total_kwh,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw

FROM dbo.meter_readings

WHERE building_id = @building_id
  AND temperature_c IS NOT NULL

GROUP BY
    CAST(ts AS date)

ORDER BY
    day ASC;


/*
===============================================================================
12. OCCUPANCY VS ENERGY
===============================================================================
*/

SELECT
    CAST(ts AS date) AS day,

    ROUND(
        AVG(CAST(occupancy AS FLOAT)),
        2
    ) AS average_occupancy,

    ROUND(
        SUM(energy_kwh),
        3
    ) AS total_kwh,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw

FROM dbo.meter_readings

WHERE building_id = @building_id
  AND occupancy IS NOT NULL

GROUP BY
    CAST(ts AS date)

ORDER BY
    day ASC;


/*
===============================================================================
13. DAILY LOAD FACTOR
===============================================================================
*/

SELECT
    CAST(ts AS date) AS day,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw,

    ROUND(
        AVG(demand_kw) /
        NULLIF(
            MAX(demand_kw),
            0
        ),
        4
    ) AS load_factor

FROM dbo.meter_readings

WHERE building_id = @building_id

GROUP BY
    CAST(ts AS date)

ORDER BY
    day ASC;


/*
===============================================================================
14. PEAK DEMAND EVENT
===============================================================================
*/

SELECT TOP (1)
    id,
    building_id,
    ts,
    demand_kw,
    energy_kwh,
    temperature_c,
    occupancy,
    hvac_kw,
    lighting_kw,
    source

FROM dbo.meter_readings

WHERE building_id = @building_id

ORDER BY
    demand_kw DESC,
    ts DESC,
    id DESC;


/*
===============================================================================
15. TOP DAILY PEAK DEMAND EVENTS
===============================================================================
*/

WITH ranked AS
(
    SELECT
        id,
        building_id,
        ts,
        demand_kw,
        energy_kwh,
        temperature_c,
        occupancy,
        hvac_kw,
        lighting_kw,
        source,

        ROW_NUMBER() OVER
        (
            PARTITION BY
                CAST(ts AS date)

            ORDER BY
                demand_kw DESC,
                ts DESC,
                id DESC
        ) AS daily_rank

    FROM dbo.meter_readings

    WHERE building_id = @building_id
)

SELECT
    building_id,

    CAST(ts AS date) AS day,

    ts,
    demand_kw,
    energy_kwh,
    temperature_c,
    occupancy,
    hvac_kw,
    lighting_kw,
    source

FROM ranked

WHERE daily_rank <= @event_count

ORDER BY
    day DESC,
    demand_kw DESC,
    ts DESC;


/*
===============================================================================
16. DATA QUALITY SUMMARY
===============================================================================
*/

SELECT
    COUNT(*) AS total_rows,

    SUM(
        CASE
            WHEN ts IS NULL
            THEN 1
            ELSE 0
        END
    ) AS missing_timestamp_rows,

    SUM(
        CASE
            WHEN demand_kw IS NULL
              OR demand_kw < 0
            THEN 1
            ELSE 0
        END
    ) AS invalid_demand_rows,

    SUM(
        CASE
            WHEN energy_kwh IS NULL
              OR energy_kwh < 0
            THEN 1
            ELSE 0
        END
    ) AS invalid_energy_rows,

    SUM(
        CASE
            WHEN temperature_c IS NULL
            THEN 1
            ELSE 0
        END
    ) AS missing_temperature_rows,

    SUM(
        CASE
            WHEN occupancy IS NULL
            THEN 1
            ELSE 0
        END
    ) AS missing_occupancy_rows,

    SUM(
        CASE
            WHEN hvac_kw IS NULL
            THEN 1
            ELSE 0
        END
    ) AS missing_hvac_rows,

    SUM(
        CASE
            WHEN lighting_kw IS NULL
            THEN 1
            ELSE 0
        END
    ) AS missing_lighting_rows

FROM dbo.meter_readings

WHERE building_id = @building_id;


/*
===============================================================================
17. DATA COVERAGE + GAP ANALYSIS
===============================================================================
*/

WITH ordered AS
(
    SELECT
        id,
        ts,

        LAG(ts) OVER
        (
            ORDER BY
                ts,
                id
        ) AS previous_ts

    FROM dbo.meter_readings

    WHERE building_id = @building_id
),

intervals AS
(
    SELECT
        ts,
        previous_ts,

        DATEDIFF(
            SECOND,
            previous_ts,
            ts
        ) / 60.0 AS interval_minutes

    FROM ordered

    WHERE previous_ts IS NOT NULL
),

coverage AS
(
    SELECT
        MIN(previous_ts) AS first_reading,

        MAX(ts) AS last_reading,

        COUNT(*) + 1 AS observed_intervals,

        DATEDIFF(
            SECOND,
            MIN(previous_ts),
            MAX(ts)
        ) / 60.0 AS observed_minutes,

        SUM(
            CASE
                WHEN interval_minutes >
                     @expected_interval_min * 1.5
                THEN 1
                ELSE 0
            END
        ) AS gap_count

    FROM intervals
)

SELECT
    first_reading,

    last_reading,

    observed_intervals,

    ROUND(
        observed_minutes,
        2
    ) AS observed_minutes,

    COALESCE(
        gap_count,
        0
    ) AS gap_count,

    CASE
        WHEN observed_minutes > 0
        THEN ROUND(
            CAST(observed_intervals AS FLOAT)
            /
            (
                (
                    observed_minutes
                    /
                    NULLIF(
                        CAST(@expected_interval_min AS FLOAT),
                        0
                    )
                ) + 1
            ),
            4
        )
        ELSE NULL
    END AS approximate_coverage_ratio

FROM coverage;


/*
===============================================================================
18. BUILDING LIST
===============================================================================
*/

SELECT
    building_id,

    COUNT(*) AS reading_count,

    MIN(ts) AS first_reading,

    MAX(ts) AS last_reading

FROM dbo.meter_readings

GROUP BY
    building_id

ORDER BY
    building_id ASC;


/*
===============================================================================
19. LATEST READING PER BUILDING
===============================================================================
*/

WITH ranked AS
(
    SELECT
        id,
        building_id,
        ts,
        demand_kw,
        energy_kwh,
        temperature_c,
        occupancy,
        hvac_kw,
        lighting_kw,
        source,

        ROW_NUMBER() OVER
        (
            PARTITION BY
                building_id

            ORDER BY
                ts DESC,
                id DESC
        ) AS row_num

    FROM dbo.meter_readings
)

SELECT
    building_id,
    ts,
    demand_kw,
    energy_kwh,
    temperature_c,
    occupancy,
    hvac_kw,
    lighting_kw,
    source

FROM ranked

WHERE row_num = 1

ORDER BY
    building_id ASC;


/*
===============================================================================
20. DATA FRESHNESS
===============================================================================
*/

SELECT
    building_id,

    MAX(ts) AS latest_reading,

    DATEDIFF(
        SECOND,
        MAX(ts),
        SYSDATETIMEOFFSET()
    ) AS data_age_seconds,

    CASE
        WHEN MAX(ts) IS NULL
            THEN N'NO_DATA'

        WHEN MAX(ts) >= DATEADD(
            MINUTE,
            -5,
            SYSDATETIMEOFFSET()
        )
            THEN N'FRESH'

        WHEN MAX(ts) >= DATEADD(
            HOUR,
            -1,
            SYSDATETIMEOFFSET()
        )
            THEN N'STALE'

        ELSE N'OFFLINE'
    END AS freshness_status

FROM dbo.meter_readings

WHERE building_id = @building_id

GROUP BY
    building_id;


/*
===============================================================================
21. SOURCE BREAKDOWN
===============================================================================
*/

WITH source_counts AS
(
    SELECT
        COALESCE(
            NULLIF(
                LTRIM(RTRIM(source)),
                N''
            ),
            N'unknown'
        ) AS source,

        COUNT(*) AS reading_count

    FROM dbo.meter_readings

    WHERE building_id = @building_id

    GROUP BY
        COALESCE(
            NULLIF(
                LTRIM(RTRIM(source)),
                N''
            ),
            N'unknown'
        )
)

SELECT
    source,

    reading_count,

    ROUND(
        CAST(reading_count AS FLOAT)
        /
        NULLIF(
            CAST(
                SUM(reading_count) OVER ()
                AS FLOAT
            ),
            0
        ) * 100,
        2
    ) AS percentage

FROM source_counts

ORDER BY
    reading_count DESC,
    source ASC;


/*
===============================================================================
22. HVAC / LIGHTING CONTRIBUTION
===============================================================================
*/

WITH readings AS
(
    SELECT
        id,
        ts,
        energy_kwh,
        hvac_kw,
        lighting_kw,

        LEAD(ts) OVER
        (
            ORDER BY
                ts,
                id
        ) AS next_ts

    FROM dbo.meter_readings

    WHERE building_id = @building_id
),

intervals AS
(
    SELECT
        id,
        ts,
        energy_kwh,
        hvac_kw,
        lighting_kw,

        DATEDIFF(
            SECOND,
            ts,
            next_ts
        ) / 3600.0 AS interval_hours

    FROM readings

    WHERE next_ts IS NOT NULL
),

valid_intervals AS
(
    SELECT
        *
    FROM intervals

    WHERE interval_hours > 0
      AND interval_hours <= @max_interval_hours
)

SELECT
    ROUND(
        SUM(energy_kwh),
        3
    ) AS measured_total_kwh,

    ROUND(
        SUM(
            COALESCE(hvac_kw, 0)
            * interval_hours
        ),
        3
    ) AS estimated_hvac_kwh,

    ROUND(
        SUM(
            COALESCE(lighting_kw, 0)
            * interval_hours
        ),
        3
    ) AS estimated_lighting_kwh,

    COUNT(*) AS valid_intervals

FROM valid_intervals;


/*
===============================================================================
23. RECENT LOAD PROFILE
===============================================================================
*/

SELECT
    id,
    ts,
    demand_kw,
    energy_kwh,
    temperature_c,
    occupancy,
    hvac_kw,
    lighting_kw

FROM
(
    SELECT TOP (@limit)
        id,
        ts,
        demand_kw,
        energy_kwh,
        temperature_c,
        occupancy,
        hvac_kw,
        lighting_kw

    FROM dbo.meter_readings

    WHERE building_id = @building_id

    ORDER BY
        ts DESC,
        id DESC
) AS recent

ORDER BY
    ts ASC,
    id ASC;


/*
===============================================================================
24. DAILY HVAC / LIGHTING / TOTAL ENERGY
===============================================================================
*/

WITH readings AS
(
    SELECT
        id,
        ts,
        energy_kwh,
        hvac_kw,
        lighting_kw,

        LEAD(ts) OVER
        (
            ORDER BY
                ts,
                id
        ) AS next_ts

    FROM dbo.meter_readings

    WHERE building_id = @building_id
),

intervals AS
(
    SELECT
        CAST(ts AS date) AS day,

        energy_kwh,
        hvac_kw,
        lighting_kw,

        DATEDIFF(
            SECOND,
            ts,
            next_ts
        ) / 3600.0 AS interval_hours

    FROM readings

    WHERE next_ts IS NOT NULL
)

SELECT
    day,

    ROUND(
        SUM(energy_kwh),
        3
    ) AS total_kwh,

    ROUND(
        SUM(
            CASE
                WHEN interval_hours > 0
                 AND interval_hours <= @max_interval_hours
                THEN COALESCE(hvac_kw, 0)
                     * interval_hours
                ELSE 0
            END
        ),
        3
    ) AS hvac_kwh,

    ROUND(
        SUM(
            CASE
                WHEN interval_hours > 0
                 AND interval_hours <= @max_interval_hours
                THEN COALESCE(lighting_kw, 0)
                     * interval_hours
                ELSE 0
            END
        ),
        3
    ) AS lighting_kwh

FROM intervals

GROUP BY
    day

ORDER BY
    day ASC;


/*
===============================================================================
25. TEMPERATURE / OCCUPANCY / DEMAND SUMMARY
===============================================================================
*/

SELECT
    CAST(ts AS date) AS day,

    ROUND(
        AVG(temperature_c),
        2
    ) AS average_temperature_c,

    ROUND(
        MIN(temperature_c),
        2
    ) AS minimum_temperature_c,

    ROUND(
        MAX(temperature_c),
        2
    ) AS maximum_temperature_c,

    ROUND(
        AVG(CAST(occupancy AS FLOAT)),
        2
    ) AS average_occupancy,

    ROUND(
        AVG(demand_kw),
        3
    ) AS average_demand_kw,

    ROUND(
        MAX(demand_kw),
        3
    ) AS peak_demand_kw,

    ROUND(
        SUM(energy_kwh),
        3
    ) AS total_kwh

FROM dbo.meter_readings

WHERE building_id = @building_id

GROUP BY
    CAST(ts AS date)

ORDER BY
    day ASC;


/*
===============================================================================
END OF QUERY LIBRARY
===============================================================================
*/