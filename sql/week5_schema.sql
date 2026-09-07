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

SHOW TABLES;

SELECT
    table_schema,
    table_name
FROM information_schema.tables
WHERE table_schema = 'microgrid_analysis'
  AND table_name = 'sites';


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
        Foreign Key (site_id) REFERENCES sites(site_id),

    CONSTRAINT chk_simulation_runs_time_range
        CHECK (analysis_end_utc > analysis_start_utc),

    CONSTRAINT chk_simulation_runs_timestep
        CHECK (timestep_minutes > 0),
    
    CONSTRAINT chk_simulation_runs_interval_count
        CHECK (interval_count > 0)
);


SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'microgrid_analysis'
  AND table_name = 'simulation_runs';


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

SELECT constraint_name
FROM information_schema.table_constraints
WHERE table_schema = 'microgrid_analysis'
  AND table_name = 'signal_sources'
  AND constraint_type = 'UNIQUE';


ALTER TABLE signal_sources
ADD CONSTRAINT uq_signal_sources_snapshot_sha256
UNIQUE (snapshot_sha256);
