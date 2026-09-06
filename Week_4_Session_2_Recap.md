# Week 4 Session 2 Recap - Five-Scenario QSTS Validation

## Completion Status

Week 4 Session 2 is complete.

Five dispatch strategies built from the same two-day real-market
input were replayed through the same OpenDSS network model at
15-minute resolution. The workflow now loads, replays, compares, and
saves every required scenario reproducibly.

## Common Real-Signal Input

The common input contains 192 intervals from August 25 through
August 26, 2026 in the `America/Los_Angeles` timezone. Every scenario
uses identical timestamps, load, PV, CAISO price, and Electricity Maps
carbon-intensity signals.

The canonical input is saved as:

```text
results/week4_real_market_inputs_15min.csv
```

## Required Dispatch Scenarios

The following OpenDSS-ready schedules were generated and saved:

- `no_battery`
- `rule_based`
- `cost_optimal`
- `carbon_optimal`
- `combined_optimal`

The cost and combined optimizations can include an optional linear
battery-throughput degradation cost. The no-battery case maintains
zero battery injection and constant SOC. The optimized schedules
return to their initial 10 kWh SOC, while the rule-based controller
does not impose a terminal-SOC constraint.

## Implemented Workflow

`src/qsts_simulation.py` now provides functions that:

1. Load all five dispatch schedules from an explicit filename map.
2. Replay every schedule through `replay_dispatch_timeseries()`.
3. Aggregate the electrical results with
   `create_qsts_scenario_comparison()`.
4. Save five interval-level result files and one comparison file.
5. Run the complete workflow through the package entry point:

```bash
/usr/local/bin/python3 -m src.qsts_simulation
```

## Verified Electrical Results

All five scenarios completed 192 converged and feasible intervals.
Every scenario had:

- Zero voltage-violation intervals
- Zero line-overload intervals
- Zero transformer-overload intervals
- Minimum voltage of approximately 0.998199 pu
- Maximum line loading of approximately 4.803890%
- Maximum transformer loading of approximately 4.260129%

| Scenario | Reverse-flow intervals | Grid import (kWh) | Grid export (kWh) | Feeder loss (kWh) | Transformer loss (kWh) |
|---|---:|---:|---:|---:|---:|
| No battery | 8 | 743.960171 | 6.769360 | 0.145018 | 0.222751 |
| Rule based | 0 | 743.963149 | 0.000000 | 0.144788 | 0.222398 |
| Cost optimal | 0 | 738.127904 | 0.000000 | 0.142722 | 0.219224 |
| Carbon optimal | 0 | 740.463461 | 0.000000 | 0.140462 | 0.215754 |
| Combined optimal | 0 | 738.802394 | 0.000000 | 0.141505 | 0.217355 |

The no-battery case exported during eight high-PV intervals. All four
battery strategies absorbed enough surplus PV to eliminate reverse
power flow in this dataset. Carbon-optimal dispatch produced the
lowest feeder and transformer loss energy, but that does not by itself
make it the best economic strategy because each optimizer follows a
different objective.

## Saved QSTS Artifacts

The reproducible outputs are:

```text
results/week4_qsts_no_battery_15min.csv
results/week4_qsts_rule_based_15min.csv
results/week4_qsts_cost_optimal_15min.csv
results/week4_qsts_carbon_optimal_15min.csv
results/week4_qsts_combined_optimal_15min.csv
results/week4_qsts_scenario_comparison.csv
```

Each interval-level file includes convergence, voltage, line loading,
transformer loading, PCC import/export, reverse-flow, loss, violation,
and overall feasibility fields.

## Validation

- All five schedules contain 192 intervals with matching common
  signals.
- All 960 OpenDSS interval solutions converged.
- Power-balance errors were negligible.
- QSTS comparison calculations are covered by an automated test.
- Result-file saving is covered using pytest's temporary directory.
- The full automated suite passed: 63 tests in 13.47 seconds.

Run the suite with:

```bash
/usr/local/bin/python3 -m pytest -q
```

## Remaining Week 4 Work

- Produce the complete Week 4 validation report linking dispatch
  objectives and schedules to their electrical outcomes.
- Review the revised Week 3 and Week 4 completion evidence against
  Gate C.
- Confirm that every Gate C requirement is satisfied before beginning
  revised Week 5 SQL work.

## Exact Next Step

Begin the final Week 4 validation report by combining the dispatch
scenario definitions, real-signal provenance, interval feasibility,
and five-scenario comparison into one traceable Gate C artifact.
