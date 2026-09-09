CREATE INDEX idx_measurements_source_name_time
ON measurements (
    signal_source_id,
    measurement_name,
    measured_at_utc
);

SHOW INDEX FROM measurements
WHERE Key_name = 'idx_measurements_source_name_time';

EXPLAIN SELECT
    measured_at_utc,
    measurement_value
FROM measurements
WHERE signal_source_id = 1
  AND measurement_name = 'energy_price'
ORDER BY measured_at_utc;