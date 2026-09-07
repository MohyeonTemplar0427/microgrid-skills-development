# Week 5 Session 2 Recap - Python and MySQL Integration

> Temporary session recap. Merge this material into the final Week 5
> completion recap after all Week 5 sessions are finished.

## Session Purpose

This session connected the Python analysis workflow to the Week 5 MySQL
database. The goal was to preserve the Week 4 input signals as structured,
queryable measurements while retaining their timestamp, engineering meaning,
unit, and provenance.

## Data Flow

```text
Week 4 integrated input CSV
            |
            v
      pandas DataFrame
            |
            v
create_measurement_rows()
            |
            v
normalized measurement tuples
            |
            v
upsert_measurement_rows()
            |
            v
MySQL measurements table
```

The source CSV stores one interval as a wide row with separate columns for
load, PV, net load, price, and carbon intensity. The database uses a long
format in which each signal at each timestamp is a separate measurement row.
For 192 intervals and five signals, the transformation produces 960 rows.

## Connector and Transaction Concepts

`mysql-connector-python` is the client library that allows Python to open an
authenticated session with MySQL, send parameterized statements, translate
Python values into SQL values, and control transactions.

Private connection settings are read from `src/.env`, which is excluded from
Git. Application code connects as `microgrid_app@localhost` to the
`microgrid_analysis` database instead of using the administrative root user.

A cursor sends SQL through an open connection. `executemany()` applies one
parameterized statement to a collection of measurement tuples. `commit()`
makes the complete successful batch permanent. `rollback()` cancels the batch
when MySQL raises an error, preventing a partially loaded input snapshot.

## Function Roles

| Function | Role |
|---|---|
| `create_database_connection()` | Opens a MySQL connection using private environment settings. |
| `get_database_identity()` | Reports the selected database and authenticated MySQL account for connection verification. |
| `create_measurement_rows()` | Converts the wide pandas input table into normalized, unit-labeled MySQL measurement tuples. |
| `upsert_measurement_rows()` | Inserts or updates a batch atomically and rolls it back if a database error occurs. |

`UPSERT_MEASUREMENTS_SQL` uses parameter placeholders rather than formatting
values into SQL text. Its unique-key conflict handling makes repeated loading
idempotent: an existing source, timestamp, and measurement name is updated
instead of duplicated.

## Timestamp and Numeric Handling

Every input timestamp must contain timezone information. Python converts it to
UTC before removing the timezone marker for storage in MySQL `DATETIME(6)`.
This preserves the actual operating interval and avoids ambiguity between
local time and UTC.

Measurement values are converted through `Decimal(str(value))`. This avoids
introducing unnecessary binary floating-point artifacts before values are
stored in fixed-precision MySQL decimal columns.

## Engineering SQL Checks

The session completed ten reusable SQL queries covering:

- simulation-run and site relationships;
- signal-source provenance;
- interval-level measurement inspection;
- foundational table and signal counts;
- missing-interval detection with `GROUP BY` and `HAVING`;
- minimum, maximum, and average signal values;
- highest-price interval identification;
- conversion of 15-minute power measurements into energy;
- total load, PV, and net-load energy balance; and
- interval-level verification that `net load = load - PV`.

Conditional aggregation with `CASE` reconstructs load, PV, and net load as
columns for each timestamp. `ABS()` and a small tolerance identify only
meaningful power-balance errors. No invalid intervals were found.

## Validation Status

The complete input snapshot was loaded successfully:

- 192 intervals;
- five input signals per interval;
- 960 normalized measurement rows; and
- 192 rows for each measurement name.

Seven database unit tests pass. They verify:

1. normal DataFrame-to-measurement transformation and UTC conversion;
2. rejection of a nonpositive signal-source identifier;
3. rejection of missing measurement columns;
4. rejection of timestamps without timezone information;
5. commit behavior for a successful database batch;
6. rollback and error propagation for a failed database batch; and
7. empty-batch handling without unnecessary database activity.

The transaction tests use `MagicMock`, so they verify database interactions
without changing the live MySQL database.

## Next Starting Point

Week 5 Session 2 is complete for the planned scope. The next session will add
storage for dispatch and OpenDSS power-flow results, load the Week 4 scenario
outputs, and connect operating decisions to their electrical consequences
through SQL relationships and engineering queries.
