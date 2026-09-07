INSERT INTO sites (
    site_name,
    timezone_name,
    description
)
VALUES (
    'training_microgrid',
    'America/Los_Angeles',
    'Three-phase microgrid model for dispatch and OpenDSS validation'
)
ON DUPLICATE KEY UPDATE
    timezone_name = 'America/Los_Angeles',
    description = 'Three-phase microgrid model for dispatch and OpenDSS validation';

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
)
ON DUPLICATE KEY UPDATE
    analysis_end_utc = '2026-08-27 07:00:00.000000',
    timestep_minutes = 15,
    interval_count = 192,
    configuration_json = '{"scenario_count": 5, "input_file": "results/week4_real_market_inputs_15min.csv", "power_flow_model": "OpenDSS"}';

-- Records the integrated input snapshot used by the Week 4 analysis.
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
VALUES (
    'week4_integrated_market_inputs',
    'integrated_timeseries',
    'CAISO, Electricity Maps, and synthetic profiles',
    NULL,
    '2026-09-05 23:29:02.000000',
    '{"start_date": "2026-08-25", "number_of_days": 2, "caiso_node": "TH_NP15_GEN-APND", "electricity_maps_zone": "US-CAL-CISO"}',
    'results/week4_real_market_inputs_15min.csv',
    '4db99df70bce4bcaa428fb9ead57c1e8a43a4e587bdd2bf35d75d18337b8d40b'
)
-- NEW: update its metadata when this file fingerprint already exists.
ON DUPLICATE KEY UPDATE
    source_name = 'week4_integrated_market_inputs',
    signal_type = 'integrated_timeseries',
    provider_name = 'CAISO, Electricity Maps, and synthetic profiles',
    retrieved_at_utc = '2026-09-05 23:29:02.000000',
    query_parameters_json = '{"start_date": "2026-08-25", "number_of_days": 2, "caiso_node": "TH_NP15_GEN-APND", "electricity_maps_zone": "US-CAL-CISO"}',
    snapshot_path = 'results/week4_real_market_inputs_15min.csv';


-- Links the Week 4 simulation run to its integrated input snapshot.
INSERT INTO simulation_run_signal_sources (
    simulation_run_id,
    signal_source_id,
    source_role
)
VALUES (
    1,
    1,
    'common_interval_input'
)
ON DUPLICATE KEY UPDATE
    source_role = 'common_interval_input';


-- Seeds the five input signals from the first Week 4 interval.
INSERT INTO measurements (
    signal_source_id,
    measured_at_utc,
    measurement_name,
    measurement_value,
    unit
)
VALUES
    (1, '2026-08-25 07:00:00.000000', 'load', 15.0, 'kW'),
    (1, '2026-08-25 07:00:00.000000', 'pv', 0.0, 'kW'),
    (1, '2026-08-25 07:00:00.000000', 'net_load', 15.0, 'kW'),
    (1, '2026-08-25 07:00:00.000000', 'energy_price', 0.06127028, '$/kWh'),
    (1, '2026-08-25 07:00:00.000000', 'carbon_intensity', 345, 'gCO2/kWh')
AS new
ON DUPLICATE KEY UPDATE
    measurement_value = new.measurement_value,
    unit = new.unit;
