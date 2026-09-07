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