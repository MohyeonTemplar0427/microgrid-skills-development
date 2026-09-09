-- Stores each modeled microgrid site and its location context.
CREATE TABLE IF NOT EXISTS sites (
    site_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    site_name VARCHAR(100) NOT NULL,
    timezone_name VARCHAR(64) NOT NULL,
    description VARCHAR(255) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (site_id),
    CONSTRAINT uq_sites_site_name UNIQUE(site_name)
);

-- Stores each reproducible analysis run, including its time window
-- resolution, code version, and configuration.
CREATE TABLE IF NOT EXISTS simulation_runs (
    simulation_run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    site_id BIGINT UNSIGNED NOT NULL,
    run_name VARCHAR(150) NOT NULL,
    analysis_start_utc DATETIME(6) NOT NULL,
    analysis_end_utc DATETIME(6) NOT NULL,
    timestep_minutes SMALLINT UNSIGNED NOT NULL,
    interval_count INT UNSIGNED NOT NULL,
    git_commit_hash CHAR(40) NULL,
    configuration_json JSON NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (simulation_run_id),
    CONSTRAINT uq_simulation_runs_identity
    UNIQUE (
        site_id,
        run_name,
        analysis_start_utc,
        git_commit_hash
    ),
    CONSTRAINT fk_simulation_runs_site
        FOREIGN KEY (site_id) REFERENCES sites(site_id),

    CONSTRAINT chk_simulation_runs_time_range
        CHECK (analysis_end_utc > analysis_start_utc),

    CONSTRAINT chk_simulation_runs_timestep
        CHECK (timestep_minutes > 0),

    CONSTRAINT chk_simulation_runs_interval_count
        CHECK (interval_count > 0)
);

-- Stores the origin, retrieval details, and saved fingerprint
-- of each load, PV, price, or carbon input dataset.
CREATE TABLE IF NOT EXISTS signal_sources (
    signal_source_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    source_name VARCHAR(150) NOT NULL,
    signal_type VARCHAR(50) NOT NULL,
    provider_name VARCHAR(100) NOT NULL,
    source_url VARCHAR(500) NULL,
    retrieved_at_utc DATETIME(6) NOT NULL,
    query_parameters_json JSON NULL,
    snapshot_path VARCHAR(500) NOT NULL,
    snapshot_sha256 CHAR(64) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (signal_source_id),
    CONSTRAINT uq_signal_sources_snapshot_sha256
        UNIQUE (snapshot_sha256)
);
-- Connects each simulation run to the input datasets it used.
-- This junction table supports a many-to-many relationship.
CREATE TABLE IF NOT EXISTS simulation_run_signal_sources (
    simulation_run_id BIGINT UNSIGNED NOT NULL,
    signal_source_id BIGINT UNSIGNED NOT NULL,
    source_role VARCHAR(50) NOT NULL,

    PRIMARY KEY (
        simulation_run_id,
        signal_source_id
    ),

    CONSTRAINT fk_run_signal_sources_run
        FOREIGN KEY (simulation_run_id)
        REFERENCES simulation_runs(simulation_run_id),

    CONSTRAINT fk_run_signal_sources_source
        FOREIGN KEY (signal_source_id)
        REFERENCES signal_sources(signal_source_id)
);

-- Stores normalized timestamped signal values from
-- each input dataset.
CREATE TABLE IF NOT EXISTS measurements (
    measurement_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    signal_source_id BIGINT UNSIGNED NOT NULL,
    measured_at_utc DATETIME(6) NOT NULL,
    measurement_name VARCHAR(50) NOT NULL,
    measurement_value DECIMAL(18, 8) NOT NULL,
    unit VARCHAR(20) NOT NULL,

    PRIMARY KEY (measurement_id),

    INDEX idx_measurements_source_name_time (
        signal_source_id,
        measurement_name,
        measured_at_utc
    ),

    CONSTRAINT uq_measurements_source_time_name
        UNIQUE (
            signal_source_id,
            measured_at_utc,
            measurement_name
        ),

    CONSTRAINT fk_measurements_signal_source
        FOREIGN KEY (signal_source_id)
        REFERENCES signal_sources(signal_source_id)
);
-- Stores each scenario's scheduled battery operation and
-- grid exchange for every interval of a simulation run.
CREATE TABLE IF NOT EXISTS dispatch_results (
    dispatch_result_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    simulation_run_id BIGINT UNSIGNED NOT NULL,
    scenario_name VARCHAR(50) NOT NULL,
    dispatched_at_utc DATETIME(6) NOT NULL,

    battery_charge_kw DECIMAL(18, 8) NOT NULL,
    battery_discharge_kw DECIMAL(18, 8) NOT NULL,
    battery_net_injection_kw DECIMAL(18, 8) NOT NULL,
    battery_soc_kwh DECIMAL(18, 8) NOT NULL,

    grid_import_kw DECIMAL(18, 8) NOT NULL,
    grid_export_kw DECIMAL(18, 8) NOT NULL,
    grid_net_import_kw DECIMAL(18, 8) NOT NULL,

    created_at TIMESTAMP(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (dispatch_result_id),

    CONSTRAINT uq_dispatch_results_run_scenario_time
        UNIQUE (
            simulation_run_id,
            scenario_name,
            dispatched_at_utc
        ),

    CONSTRAINT fk_dispatch_results_run
        FOREIGN KEY (simulation_run_id)
        REFERENCES simulation_runs(simulation_run_id),

    CONSTRAINT chk_dispatch_results_nonnegative_values
        CHECK (
            battery_charge_kw >= 0
            AND battery_discharge_kw >= 0
            AND battery_soc_kwh >= 0
            AND grid_import_kw >= 0
            AND grid_export_kw >= 0
        )
);
-- Stores the OpenDSS electrical result produced by replaying
-- one scheduled dispatch operating point.
CREATE TABLE IF NOT EXISTS powerflow_results (
    powerflow_result_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dispatch_result_id BIGINT UNSIGNED NOT NULL,

    converged BOOLEAN NOT NULL,
    voltage_violation BOOLEAN NOT NULL,
    line_overload BOOLEAN NOT NULL,
    transformer_overload BOOLEAN NOT NULL,
    reverse_power_flow BOOLEAN NOT NULL,
    feasible BOOLEAN NOT NULL,

    minimum_voltage_pu DECIMAL(18, 8) NOT NULL,
    maximum_voltage_pu DECIMAL(18, 8) NOT NULL,
    maximum_current_a DECIMAL(18, 8) NOT NULL,

    line_normal_rating_a DECIMAL(18, 8) NOT NULL,
    line_loading_percent DECIMAL(18, 8) NOT NULL,

    transformer_apparent_power_kva DECIMAL(18, 8) NOT NULL,
    transformer_loading_percent DECIMAL(18, 8) NOT NULL,
    transformer_real_loss_kw DECIMAL(18, 8) NOT NULL,
    feeder_input_real_power_kw DECIMAL(18, 8) NOT NULL,
    feeder_real_loss_kw DECIMAL(18, 8) NOT NULL,

    pcc_grid_net_import_kw DECIMAL(18, 8) NOT NULL,
    pcc_grid_import_kw DECIMAL(18, 8) NOT NULL,
    pcc_grid_export_kw DECIMAL(18, 8) NOT NULL,

    receiving_end_real_power_kw DECIMAL(18, 8) NOT NULL,
    grid_import_error_kw DECIMAL(18, 8) NOT NULL,

    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (powerflow_result_id),

    CONSTRAINT uq_powerflow_results_dispatch UNIQUE (dispatch_result_id),
    CONSTRAINT fk_powerflow_results_dispatch FOREIGN KEY (dispatch_result_id)
        REFERENCES dispatch_results(dispatch_result_id),

    CONSTRAINT chk_powerflow_results_nonnegative_values
        CHECK (
            minimum_voltage_pu >= 0
            AND maximum_voltage_pu >= 0
            AND maximum_current_a >= 0
            AND line_normal_rating_a >= 0
            AND line_loading_percent >= 0
            AND transformer_apparent_power_kva >= 0
            AND transformer_real_loss_kw >= 0
            AND feeder_real_loss_kw >= 0
            AND pcc_grid_import_kw >= 0
            AND pcc_grid_export_kw >= 0
        ),

    CONSTRAINT chk_powerflow_results_transformer_loading
        CHECK (transformer_loading_percent >= 0)
);
