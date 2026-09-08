-- Query 1: Show each simulation run with its physical site.
SELECT
    sr.simulation_run_id,
    sr.run_name,
    s.site_name,
    s.timezone_name
FROM simulation_runs AS sr
INNER JOIN sites AS s
    ON sr.site_id = s.site_id;

-- Query 2: Show the provenance of each simulation run's inputs.
SELECT
    sr.simulation_run_id,
    sr.run_name,
    rss.source_role,
    ss.source_name,
    ss.provider_name,
    ss.snapshot_path
FROM simulation_runs AS sr
INNER JOIN simulation_run_signal_sources AS rss
    ON sr.simulation_run_id = rss.simulation_run_id

INNER JOIN signal_sources as ss
    ON rss.signal_source_id = ss.signal_source_id

ORDER BY sr.simulation_run_id;

SHOW CREATE TABLE simulation_run_signal_sources;

-- Query 3: Inspect all signals recorded for one interval.
SELECT
    measured_at_utc,
    measurement_name,
    measurement_value,
    unit
FROM measurements
WHERE measured_at_utc = '2026-08-25 07:00:00.000000'
ORDER BY measurement_name;

-- Query 4: Validate the number of foundational records in each table.
SELECT
    'sites' AS table_name,
    COUNT(*) AS row_count
FROM sites

UNION ALL

SELECT
    'simulation_runs' AS table_name,
    COUNT(*) AS row_count
FROM simulation_runs

UNION ALL

SELECT
    'signal_sources' AS table_name,
    COUNT(*) AS row_count
FROM signal_sources

UNION ALL

SELECT
    'simulation_run_signal_sources' AS table_name,
    COUNT(*) AS row_count
FROM simulation_run_signal_sources

UNION ALL

SELECT
    'measurements' AS table_name,
    COUNT(*) AS row_count
FROM measurements;

-- Query 5: Verify the interval count for each input signal.
SELECT
    measurement_name,
    COUNT(*) AS interval_count
FROM measurements
GROUP BY measurement_name
ORDER BY measurement_name;

-- Query 6: Report input signals that do not contain 192 intervals
-- HAVING filters completed groups after GROUP BY
-- <> means "not equal to"
SELECT measurement_name, COUNT(*) AS interval_count
FROM measurements
WHERE signal_source_id = 1
GROUP BY measurement_name
HAVING count(*) <> 192
ORDER BY measurement_name;

-- Query 7: Summarize the range and average of each input signal.
SELECT
    measurement_name,
    unit,
    MIN(measurement_value) AS minimum_value,
    MAX(measurement_value) AS maximum_value,
    AVG(measurement_value) AS average_value
FROM measurements
WHERE signal_source_id = 1
GROUP BY measurement_name, unit
ORDER BY measurement_name;

-- Query 8: Find the five highest-price intervals.
SELECT
    measured_at_utc,
    measurement_value AS energy_price_per_kWh
FROM measurements
WHERE signal_source_id = 1 AND measurement_name = 'energy_price'
ORDER BY measurement_value DESC
limit 5;

-- Query 9: Calculate total load, PV, and net-load energy.
SELECT
    measurement_name, ROUND(SUM(measurement_value * 0.25),3) AS energy_kWh
FROM measurements
WHERE signal_source_id = 1
    AND measurement_name IN (
        'load',
        'pv',
        'net_load'
    )
GROUP BY measurement_name
ORDER BY measurement_name;

-- Query 10, identifies intervals with an invalid power balance
SELECT
    measured_at_utc,
    MAX(
        CASE
            WHEN measurement_name = 'load'
            THEN measurement_value
        END
    ) AS load_kw,

    MAX(
        CASE
            WHEN measurement_name = 'pv'
            THEN measurement_value
        END
    ) AS pv_kw,

    MAX(
        CASE
            WHEN measurement_name = 'net_load'
            THEN measurement_value
        END
    ) AS net_load_kw

FROM measurements

WHERE signal_source_id = 1
    AND measurement_name IN (
        'load',
        'pv',
        'net_load'
    )
GROUP BY measured_at_utc

HAVING ABS(
    MAX(
        CASE
            WHEN measurement_name = 'net_load'
            THEN measurement_value
        END
    )
    -
    (
    MAX(
        CASE 
            WHEN measurement_name = 'load' 
            THEN measurement_value  
        END
    )
    -
    MAX(
        CASE 
            WHEN measurement_name = 'pv' 
            THEN measurement_value  
        END
    )
    )
) > 0.000001

ORDER BY measured_at_utc;


-- Query 11 checks each dispatch scenario against the interval count
-- recorded in its simulation-run metadata
SELECT
    dr.simulation_run_id,
    dr.scenario_name,
    COUNT(*) AS stored_interval_count,
    sr.interval_count AS expected_interval_count,

    CASE 
        WHEN COUNT(*) = sr.interval_count THEN 'complete'  
        ELSE 'incomplete'
    END AS load_status

FROM dispatch_results AS dr

INNER JOIN simulation_runs AS sr
    ON dr.simulation_run_id = sr.simulation_run_id

WHERE dr.simulation_run_id = 1

GROUP BY dr.simulation_run_id, dr.scenario_name, sr.interval_count
ORDER BY dr.scenario_name;
