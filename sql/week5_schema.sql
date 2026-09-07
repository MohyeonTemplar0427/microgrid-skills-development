-- Stores each modeled microgrid site and its location context.
CREATE TABLE IF NOT EXISTS sites(
    site_id BIGINT UNSIGNED NOT NULL
AUTO_INCREMENT,
    site_name VARCHAR(100) NOT NULL,
    timezone_name VARCHAR(64) NOT NULL,
    description VARCHAR(255) NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    PRIMARY KEY (site_id),
    CONSTRAINT uq_sites_site_name UNIQUE(site_name)
);

-- Stores each reproducible analysis run, including its time window
-- resolution, code version, and configuration.
CREATE TABLE IF NOT EXISTS simulation_runs(
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
CREATE TABLE IF NOT EXISTS simulation_run_signal_sources(
    simulation_run_id BIGINT UNSIGNED NOT NULL,
    signal_source_id BIGINT UNSIGNED NOT NULL,
    source_role VARCHAR(50) NOT NULL,

    PRIMARY KEY (
        simulation_run_id,
        signal_source_id
    ),

    CONSTRAINT fk_run_signal_sources_run
        FOREIGN KEY (simulation_run_id) REFERENCES simulation_runs(simulation_run_id),

    CONSTRAINT fk_run_signal_sources_source
        FOREIGN KEY (signal_source_id) REFERENCES signal_sources(signal_source_id)
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
