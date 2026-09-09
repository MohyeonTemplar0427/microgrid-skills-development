# Week 3 OpenDSS Solution Modes

## Snapshot Mode

The base feeder uses OpenDSS Snapshot mode:

```text
Set Mode=Snapshot
```

Snapshot mode solves one steady-state operating point using the
current load, PV, storage, and circuit settings.

OpenDSSDirect reports Snapshot as solution mode `0`.

The Week 3 base case uses Snapshot mode because it validates one
specific operating condition:

- Building load: 500 kW
- Building power factor: 0.95
- PV output: 0 kW
- Battery state: idling

## Daily Mode Demonstration

OpenDSS Daily mode was demonstrated using:

```text
Set Mode=Daily
Set Stepsize=15m
Set Number=4
```

OpenDSSDirect reports Daily as solution mode `1`.

The demonstration started at hour 0 and completed at:

```text
Hour: 1
Seconds: 0
```

This is correct because four 15-minute steps equal one hour.

The base circuit did not have a `LoadShape` during this
demonstration, so the electrical operating point remained unchanged.
The purpose was to verify OpenDSS time advancement and solution-mode
behavior.

## Externally Controlled QSTS

The existing `replay_dispatch_timeseries()` function does not use
OpenDSS Daily mode to control the schedule.

Instead, Python performs an externally controlled quasi-static
time-series simulation:

1. Read one 15-minute dispatch row from the pandas DataFrame.
2. Set load power.
3. Set PV irradiance.
4. Set battery power, state, and stored-energy percentage.
5. Solve one OpenDSS Snapshot operating point.
6. Record voltage, current, power, convergence, and losses.
7. Repeat for the next dispatch row.

This is equivalent to a sequence of controlled Snapshot solutions.

Python remains responsible for:

- Timestamps
- Scenario selection
- Battery dispatch
- Battery SOC
- Input validation
- Result collection

OpenDSS remains responsible for:

- Three-phase power flow
- Bus voltage
- Line current
- Transformer power
- Electrical losses
- Convergence

## Why External Control Is Used

External control provides a direct mapping between each optimizer
row and each OpenDSS result row. It also allows no-battery,
rule-based, cost-optimal, carbon-optimal, and combined schedules to
use the same circuit model.

A later Week 4 exercise may use `LoadShape` and Daily mode for a
native OpenDSS time-series comparison. The present QSTS implementation
remains valid because each 15-minute interval is explicitly applied
and solved by Python.
