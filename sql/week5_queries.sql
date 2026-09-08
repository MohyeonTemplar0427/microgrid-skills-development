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

INNER JOIN signal_sources AS ss
    ON rss.signal_source_id = ss.signal_source_id

ORDER BY sr.simulation_run_id;

-- Query 3 inspects all signals at the earliest interval of
-- the selected simulation run.
WITH run_measurements AS (
    SELECT
        sr.simulation_run_id,
        m.measured_at_utc,
        m.measurement_name,
        m.measurement_value,
        m.unit

    FROM simulation_runs AS sr

    INNER JOIN simulation_run_signal_sources AS rss
        ON sr.simulation_run_id =
           rss.simulation_run_id

    INNER JOIN measurements AS m
        ON rss.signal_source_id =
           m.signal_source_id

    WHERE sr.simulation_run_id = 1
      AND rss.source_role = 'common_interval_input'
)

SELECT
    simulation_run_id,
    measured_at_utc,
    measurement_name,
    measurement_value,
    unit

FROM run_measurements

WHERE measured_at_utc = (
    SELECT MIN(measured_at_utc)
    FROM run_measurements
)

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
FROM measurements

UNION ALL

SELECT
    'dispatch_results' AS table_name,
    COUNT(*) AS row_count
FROM dispatch_results

UNION ALL

SELECT
    'powerflow_results' AS table_name,
    COUNT(*) AS row_count
FROM powerflow_results;

-- Query 5 counts each input signal linked to the selected
-- simulation run.
SELECT
    sr.simulation_run_id,
    m.measurement_name,
    COUNT(m.measurement_id) AS interval_count

FROM simulation_runs AS sr

INNER JOIN simulation_run_signal_sources AS rss
    ON sr.simulation_run_id =
       rss.simulation_run_id

INNER JOIN measurements AS m
    ON rss.signal_source_id =
       m.signal_source_id

WHERE sr.simulation_run_id = 1
  AND rss.source_role = 'common_interval_input'

GROUP BY
    sr.simulation_run_id,
    m.measurement_name

ORDER BY m.measurement_name;

-- Query 6 reports signals whose stored row count
-- differs from the selected simulation run's expected count.
SELECT
    sr.simulation_run_id,
    ss.signal_source_id,
    m.measurement_name,

    COUNT(
        m.measurement_id
    ) AS stored_interval_count,

    sr.interval_count AS expected_interval_count

FROM simulation_runs AS sr

INNER JOIN simulation_run_signal_sources AS rss
    ON sr.simulation_run_id =
       rss.simulation_run_id

INNER JOIN signal_sources AS ss
    ON rss.signal_source_id =
       ss.signal_source_id

LEFT JOIN measurements AS m
    ON ss.signal_source_id =
       m.signal_source_id

WHERE sr.simulation_run_id = 1

GROUP BY
    sr.simulation_run_id,
    ss.signal_source_id,
    m.measurement_name,
    sr.interval_count

HAVING COUNT(m.measurement_id) <>
       sr.interval_count

ORDER BY
    ss.signal_source_id,
    m.measurement_name;

-- Query 7 summarizes each input signal linked to the
-- selected simulation run.
SELECT
    sr.simulation_run_id,
    m.measurement_name,
    m.unit,
    MIN(m.measurement_value) AS minimum_value,
    MAX(m.measurement_value) AS maximum_value,
    AVG(m.measurement_value) AS average_value

FROM simulation_runs AS sr

INNER JOIN simulation_run_signal_sources AS rss
    ON sr.simulation_run_id =
       rss.simulation_run_id

INNER JOIN measurements AS m
    ON rss.signal_source_id =
       m.signal_source_id

WHERE sr.simulation_run_id = 1
  AND rss.source_role = 'common_interval_input'

GROUP BY
    sr.simulation_run_id,
    m.measurement_name,
    m.unit

ORDER BY m.measurement_name;

-- Query 8 finds the five highest-price intervals for the
-- input source linked to the selected simulation run.
SELECT
    sr.simulation_run_id,
    m.measured_at_utc,
    m.measurement_value AS energy_price_per_kwh

FROM simulation_runs AS sr

INNER JOIN simulation_run_signal_sources AS rss
    ON sr.simulation_run_id =
       rss.simulation_run_id

INNER JOIN measurements AS m
    ON rss.signal_source_id =
       m.signal_source_id

WHERE sr.simulation_run_id = 1
  AND rss.source_role = 'common_interval_input'
  AND m.measurement_name = 'energy_price'

ORDER BY m.measurement_value DESC

LIMIT 5;

-- Query 9 calculates signal energy using the
-- timestep recorded for the selected simulation run.
SELECT
    sr.simulation_run_id,
    m.measurement_name,

    ROUND(
        SUM(m.measurement_value)
        * sr.timestep_minutes / 60.0,
        3
    ) AS energy_kwh

FROM simulation_runs AS sr

INNER JOIN simulation_run_signal_sources AS rss
    ON sr.simulation_run_id =
       rss.simulation_run_id

INNER JOIN measurements AS m
    ON rss.signal_source_id =
       m.signal_source_id

WHERE sr.simulation_run_id = 1
  AND rss.source_role = 'common_interval_input'
  AND m.measurement_name IN (
      'load',
      'pv',
      'net_load'
  )

GROUP BY
    sr.simulation_run_id,
    m.measurement_name,
    sr.timestep_minutes

ORDER BY m.measurement_name;

-- Query 10 verifies interval power balance for the input
-- source linked to the selected simulation run.
WITH interval_power AS (
    SELECT
        sr.simulation_run_id,
        m.measured_at_utc,

        MAX(
            CASE
                WHEN m.measurement_name = 'load'
                THEN m.measurement_value
            END
        ) AS load_kw,

        MAX(
            CASE
                WHEN m.measurement_name = 'pv'
                THEN m.measurement_value
            END
        ) AS pv_kw,

        MAX(
            CASE
                WHEN m.measurement_name = 'net_load'
                THEN m.measurement_value
            END
        ) AS net_load_kw

    FROM simulation_runs AS sr

    INNER JOIN simulation_run_signal_sources AS rss
        ON sr.simulation_run_id =
           rss.simulation_run_id

    INNER JOIN measurements AS m
        ON rss.signal_source_id =
           m.signal_source_id

    WHERE sr.simulation_run_id = 1
      AND rss.source_role = 'common_interval_input'
      AND m.measurement_name IN (
          'load',
          'pv',
          'net_load'
      )

    GROUP BY
        sr.simulation_run_id,
        m.measured_at_utc
)

SELECT
    simulation_run_id,
    measured_at_utc,
    load_kw,
    pv_kw,
    net_load_kw,

    ABS(
        net_load_kw - (load_kw - pv_kw)
    ) AS balance_error_kw

FROM interval_power

WHERE ABS(
    net_load_kw - (load_kw - pv_kw)
) > 0.000001

ORDER BY measured_at_utc;


-- Query 11 checks each dispatch scenario against the interval count
-- recorded in its simulation-run metadata.
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

GROUP BY
    dr.simulation_run_id,
    dr.scenario_name,
    sr.interval_count

ORDER BY dr.scenario_name;
-- Query 12 verifies that every dispatch interval has a
-- corresponding converged and feasible power-flow result.
SELECT
    dr.simulation_run_id,
    dr.scenario_name,
    sr.interval_count AS expected_interval_count,

    COUNT(
        dr.dispatch_result_id
    ) AS dispatch_interval_count,

    COUNT(
        pfr.powerflow_result_id
    ) AS powerflow_interval_count,

    SUM(
        CASE
            WHEN pfr.converged = 1 THEN 1
            ELSE 0
        END
    ) AS converged_interval_count,

    SUM(
        CASE
            WHEN pfr.feasible = 1 THEN 1
            ELSE 0
        END
    ) AS feasible_interval_count,

    CASE
        WHEN COUNT(pfr.powerflow_result_id) =
             sr.interval_count
        THEN 'complete'
        ELSE 'incomplete'
    END AS powerflow_load_status

FROM dispatch_results AS dr

INNER JOIN simulation_runs AS sr
    ON dr.simulation_run_id =
       sr.simulation_run_id

LEFT JOIN powerflow_results AS pfr
    ON dr.dispatch_result_id =
       pfr.dispatch_result_id

WHERE dr.simulation_run_id = 1

GROUP BY
    dr.simulation_run_id,
    dr.scenario_name,
    sr.interval_count

ORDER BY dr.scenario_name;

-- Query 13 summarizes the electrical performance
-- of each scenario using the run's stored timestep.
SELECT
    dr.scenario_name,

    MIN(
        pfr.minimum_voltage_pu
    ) AS minimum_voltage_pu,

    MAX(
        pfr.maximum_voltage_pu
    ) AS maximum_voltage_pu,

    MAX(
        pfr.maximum_current_a
    ) AS maximum_current_a,

    MAX(
        pfr.line_loading_percent
    ) AS maximum_line_loading_percent,

    MAX(
        pfr.transformer_loading_percent
    ) AS maximum_transformer_loading_percent,

    ROUND(
        SUM(
            pfr.pcc_grid_import_kw
            * sr.timestep_minutes / 60.0
        ),
        3
    ) AS grid_import_energy_kwh,

    ROUND(
        SUM(
            pfr.pcc_grid_export_kw
            * sr.timestep_minutes / 60.0
        ),
        3
    ) AS grid_export_energy_kwh,

    ROUND(
        SUM(
            pfr.feeder_real_loss_kw
            * sr.timestep_minutes / 60.0
        ),
        3
    ) AS feeder_loss_energy_kwh,

    ROUND(
        SUM(
            pfr.transformer_real_loss_kw
            * sr.timestep_minutes / 60.0
        ),
        3
    ) AS transformer_loss_energy_kwh,

    SUM(
        CASE
            WHEN pfr.reverse_power_flow = 1 THEN 1
            ELSE 0
        END
    ) AS reverse_power_flow_intervals,

    SUM(
        CASE
            WHEN pfr.feasible = 0 THEN 1
            ELSE 0
        END
    ) AS infeasible_intervals

FROM dispatch_results AS dr

INNER JOIN powerflow_results AS pfr
    ON dr.dispatch_result_id =
       pfr.dispatch_result_id

INNER JOIN simulation_runs AS sr
    ON dr.simulation_run_id =
       sr.simulation_run_id

WHERE dr.simulation_run_id = 1

GROUP BY
    dr.scenario_name,
    sr.timestep_minutes

ORDER BY dr.scenario_name;
