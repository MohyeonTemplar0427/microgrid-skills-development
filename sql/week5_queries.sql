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