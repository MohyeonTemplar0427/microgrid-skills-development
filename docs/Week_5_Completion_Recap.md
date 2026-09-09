# Week 5 Completion Recap - SQL, Provenance, and Reproducibility

## Purpose and Completion Status

Week 5 is complete for the current project scope.

The project now stores the information needed to reconstruct and inspect a
microgrid study: the physical site, run configuration, input provenance,
time-series signals, dispatch decisions, and OpenDSS electrical results.
Python performs the transformation and loading work, while MySQL preserves
relationships and supports reusable engineering queries.

The database-focused suite contains 10 tests, and the complete repository
suite passes 76 tests.

## Engineering Data Flow

The database separates external conditions, operational decisions, and
physical consequences:

```text
External inputs
    load, PV, price, grid carbon intensity
                    |
                    v
Dispatch decisions
    battery charge, discharge, SOC, scheduled grid exchange
                    |
                    v
OpenDSS power flow
    voltage, current, loading, losses, PCC flow, feasibility
```

This separation is important physically. A dispatch schedule states what the
controller requests. A power-flow result states what the electrical network
experiences after that request is applied. The two layers are related but are
not interchangeable because transformer and feeder losses affect actual PCC
power.

## Relational Model

```text
sites
  `--< simulation_runs
         |--< dispatch_results --1 powerflow_results
         `--< simulation_run_signal_sources >-- signal_sources
                                                   `--< measurements
```

`--<` represents a one-to-many relationship. The junction table creates the
many-to-many relationship between simulation runs and source datasets. Each
dispatch row has at most one power-flow row, enforced as a one-to-one
relationship through a unique foreign key.

The grain of each table is explicit:

| Table | Meaning of one row |
|---|---|
| `sites` | One modeled physical microgrid location. |
| `simulation_runs` | One reproducible analysis execution and its time/configuration metadata. |
| `signal_sources` | One saved input dataset and its provenance fingerprint. |
| `simulation_run_signal_sources` | One relationship between a run and an input dataset. |
| `measurements` | One named signal value from one source at one UTC timestamp. |
| `dispatch_results` | One scenario's scheduled operating decision at one timestamp. |
| `powerflow_results` | One OpenDSS electrical solution linked to one dispatch row. |

## Keys, Constraints, and Normalization

Primary keys give each entity a stable database identity. Foreign keys prevent
orphaned records. Composite unique constraints prevent duplicate measurements
and duplicate scenario intervals. Check constraints reject physically invalid
negative values for quantities such as charge power, equipment loading, and
grid import or export magnitude.

Signed net quantities deliberately allow negative values:

- negative battery net injection represents charging;
- negative grid net import represents export or reverse power flow; and
- signed error values preserve the direction of a mismatch.

The common load and PV inputs are stored once in `measurements`; they are not
duplicated in every dispatch or power-flow record. This normalization reduces
inconsistency while joins reconstruct the complete engineering context.

## Provenance and Reproducibility

A reproducible run records:

- its site and UTC analysis window;
- timestep and expected interval count;
- Git commit hash;
- JSON configuration;
- source provider and retrieval metadata;
- saved snapshot path; and
- SHA-256 fingerprint of the source snapshot.

The seed file uses stable identities rather than assuming auto-increment IDs.
Scalar subqueries locate the site by name, the run by its unique identity, and
the source by its SHA-256 fingerprint. `ON DUPLICATE KEY UPDATE` makes repeated
execution idempotent: existing logical records are updated rather than copied.

Private credentials remain in `src/.env`, which is excluded from Git. Python
connects as the dedicated `microgrid_app` account rather than the MySQL root
administrator.

## Python Connector and Transaction Model

`mysql-connector-python` provides the authenticated session between Python and
MySQL. A connection owns transaction state; a cursor sends SQL through that
connection.

Parameterized statements keep values separate from SQL text. `executemany()`
loads a collection of tuples efficiently. A successful batch is finalized by
`commit()`. A MySQL failure triggers `rollback()`, after which the original
exception is raised again. This prevents a partial scenario or measurement
batch from remaining in the database.

Input timestamps must contain timezone information. They are converted to UTC
before being stored in `DATETIME(6)`. Numeric values pass through
`Decimal(str(value))` to avoid unnecessary binary floating-point artifacts.

## Function Roles

| Function | Role |
|---|---|
| `create_database_connection()` | Opens an authenticated MySQL session from private environment settings. |
| `get_database_identity()` | Confirms the selected database and authenticated account. |
| `create_measurement_rows()` | Converts wide input intervals into normalized, unit-labeled measurement tuples. |
| `upsert_measurement_rows()` | Atomically inserts or updates measurement tuples. |
| `create_dispatch_result_rows()` | Converts one scenario schedule into timestamped dispatch tuples. |
| `upsert_dispatch_result_rows()` | Atomically inserts or updates a dispatch batch. |
| `upsert_dispatch_scenarios()` | Combines multiple scenario schedules and commits them as one batch. |
| `get_dispatch_result_id_map()` | Maps scenario and UTC timestamp pairs to stored dispatch IDs. |
| `create_powerflow_result_rows()` | Converts one QSTS result table and links each row to its dispatch ID. |
| `upsert_powerflow_result_rows()` | Atomically inserts or updates a power-flow batch. |
| `upsert_powerflow_scenarios()` | Combines and stores multiple QSTS scenarios as one batch. |
| `load_required_qsts_results()` | Loads the five saved Week 4 electrical-result artifacts without rerunning OpenDSS. |

The transformation functions are separate from persistence functions. This
makes units, timestamps, field order, and relationships testable without
changing the live database.

## SQL Concepts Applied

The Week 5 query set uses:

- `SELECT`, `WHERE`, `ORDER BY`, and `LIMIT` for retrieval;
- `MIN`, `MAX`, `AVG`, `SUM`, and `COUNT` for engineering aggregation;
- `GROUP BY` and `HAVING` for interval-completeness checks;
- `INNER JOIN` for required relationships;
- `LEFT JOIN` to preserve and expose missing related results;
- `UNION ALL` for table inventories;
- `CASE` for conditional counts and signal reconstruction;
- common table expressions for readable multi-stage analysis;
- scalar subqueries for stable record lookup; and
- `EXPLAIN` for query-plan inspection.

Engineering queries report provenance, signal statistics, energy, interval
balance, scenario completeness, voltage extrema, equipment loading, losses,
PCC exchange, reverse power flow, and feasibility.

## Longer-Horizon Readiness

Queries no longer assume a 192-interval horizon or a fixed 0.25-hour step.
Expected counts come from `simulation_runs.interval_count`, and energy uses:

```text
energy (kWh) = SUM(power in kW) * timestep_minutes / 60
```

Input sources are selected through run provenance instead of a hardcoded
signal-source ID. `simulation_run_id = 1` remains an explicit choice of the
current run; another run can be selected by changing that value or by passing
it as a parameter from application code.

The measurement table has complementary indexes:

```text
source -> timestamp -> measurement name
source -> measurement name -> timestamp
```

The first supports interval reconstruction and uniqueness. The second supports
long-horizon retrieval of one signal. `EXPLAIN` confirmed that MySQL selects
the second index for an energy-price time-series query.

For substantially larger studies, a future loader should divide rows into
configurable transaction chunks and benchmark query performance against the
target retention period.

## Validation Evidence

The current database contains one reproducible two-day study with:

- 192 intervals and five input signals;
- 960 normalized measurements;
- five dispatch scenarios and 960 dispatch rows; and
- 960 one-to-one OpenDSS power-flow results.

Completeness queries found the expected number of input, dispatch, and
power-flow intervals. Every stored electrical result converged and was
feasible for the present circuit and operating dataset. Power-balance queries
found no inconsistent load, PV, and net-load intervals.

These values validate the pipeline; they are not universal conclusions about
all microgrids. Different physical parameters, time horizons, input signals,
or control strategies can produce materially different operating results.

## Files Produced

| File | Purpose |
|---|---|
| `sql/schema.sql` | Creates the seven relational tables, constraints, and measurement index. |
| `sql/seed.sql` | Reproducibly registers the current site, run, source, relationship, and example measurements. |
| `sql/engineering_queries.sql` | Contains reusable provenance, completeness, engineering, and performance queries. |
| `src/database.py` | Implements connection, transformation, lookup, and transactional upsert functions. |
| `test/test_database.py` | Tests transformations, validation, relationships, and transaction behavior without modifying MySQL. |

## Future Development

Useful extensions include:

- configurable chunk sizes for multi-month and annual datasets;
- application-level query parameters instead of literal run IDs;
- schema migrations for controlled production database changes;
- a normalized scenario-definition table for richer control metadata;
- automated database integration tests in an isolated test schema; and
- retention, backup, and access-control policies for operational deployment.

Week 6 can now use this reproducible database layer while beginning SPICE
fundamentals and component-level electrical modeling.
