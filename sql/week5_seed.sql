INSERT INTO sites (
    site_name,
    timezone_name,
    description
)

VALUES (
    'training_microgrid',
    'America/Los_Angeles',
    'Three-phase-microgrid model for dispatch and OpenDSS validation'
);

SELECT * FROM sites;


INSERT INTO simulation_runs (
    site_id,
    run_name,
    analysis_start_utc,
    analysis_end_utc,
    timestep_minutes,
    interval_count,
    git_commit_hash,
    configuration_json
)
VALUES (
    1,
    'week4_real_market_qsts_validation',
    '2026-08-25 07:00:00.000000',
    '2026-08-27 07:00:00.000000',
    15,
    192,
    'b6cd01e5b858c56c61fd6964e3b759ac6db974be',
    '{"scenario_count": 5, "input_file": "results/week4_real_market_inputs_15min.csv", "power_flow_model": "OpenDSS"}'
);

SELECT
    simulation_run_id,
    site_id,
    run_name,
    timestep_minutes,
    interval_count,
    git_commit_hash
FROM simulation_runs
ORDER BY simulation_run_id;

start transaction;

DELETE FROM simulation_runs
WHERE simulation_run_id IN (2, 3, 4, 5, 6);


SELECT
    simulation_run_id,
    site_id,
    run_name
FROM simulation_runs
ORDER BY simulation_run_id;

commit;

ALTER TABLE simulation_runs
ADD CONSTRAINT uq_simulation_runs_identity
UNIQUE (
    site_id,
    run_name,
    analysis_start_utc,
    git_commit_hash
);

SELECT constraint_name
FROM information_schema.table_constraints
WHERE table_schema = 'microgrid_analysis'
  AND table_name = 'simulation_runs'
  AND constraint_type = 'UNIQUE';


-- Records the integrated input snapshot used by the Week 4 analysis
INSERT INTO signal_sources (
    source_name,
    signal_type,
    provider_name,
    source_url,
    retrieved_at_utc,
    query_parameters_json,
    snapshot_path,
    snapshot_sha256
)
VALUES(
    'week4_integrated_market_inputs',
    'integrated_timeseries',
    'CAISO, Electricity Maps, and synthetic profiles',
    NULL,
    '2026-09-05 23:29:02.000000',
    '{"start_date": "2026-08-25", "number_of_days": 2, "caiso_node": "TH_NP15_GEN-APND", "electricity_maps_zone": "US-CAL-CISO"}',
    'results/week4_real_market_inputs_15min.csv',
    '4db99df70bce4bcaa428fb9ead57c1e8a43a4e587bdd2bf35d75d18337b8d40b'
);

SELECT
    signal_source_id,
    source_name,
    signal_type,
    provider_name,
    snapshot_path,
    snapshot_sha256
FROM signal_sources;

-- Links the Week 4 simulation run to its integrated input snapshot.
INSERT INTO simulation_run_signal_sources(
    simulation_run_id,
    signal_source_id,
    source_role
)
VALUES (
    1,
    1,
    'common_interval_input'
);

SELECT *
FROM simulation_run_signal_sources;

