# Week 2 Completion Recap

## Objective

Week 2 consolidated the Week 1 microgrid optimizer into a validated real-data pipeline and produced a trustworthy handoff for later OpenDSS replay.

## Data validation completed

The pipeline now verifies:

- required columns;
- expected row counts;
- missing and non-finite values;
- numeric signal values;
- unique and ordered timestamps;
- timezone-aware Pacific timestamps;
- continuous 15-minute intervals;
- one-to-one merge cardinality;
- identical timestamp coverage across load, price, carbon, and dispatch data.

## Real-signal scenarios

Four optimized scenarios are evaluated against the same realized CAISO price and Electricity Maps carbon signals:

1. Synthetic price and synthetic carbon
2. Real price and synthetic carbon
3. Synthetic price and real carbon
4. Real price and real carbon

All scenarios use a common no-battery baseline.

## Selected result

The combined-real strategy with carbon weight 0.2 was selected for the OpenDSS handoff because it achieved both:

- operating-cost savings after degradation: approximately $0.581;
- emissions reduction: approximately 2.352 kgCO2.

The carbon-weight 0.5 case reduced emissions further, by approximately 4.668 kgCO2, but increased total operating cost after degradation by approximately $0.164.

## Reproducible artifacts

- `results/week2_market_signal_scenario_comparison.csv`
- `results/week2_opendss_handoff_combined_real_15min.csv`
- `results/week2_opendss_handoff_combined_real_15min_metadata.json`

The OpenDSS handoff contains 192 continuous 15-minute intervals in `America/Los_Angeles`.

## OpenDSS sign conventions

- `battery_net_injection_kw = battery_discharge_kw - battery_charge_kw`
  - Positive supplies the feeder.
  - Negative consumes from the feeder.
- `grid_net_import_kw = grid_import_kw - grid_export_kw`
  - Positive imports from the utility.
  - Negative exports to the utility.

Power is measured in kW, battery state of charge in kWh, and timestamps use ISO 8601 Pacific time.

Solver values with absolute magnitude below `1e-6 kW` are normalized to zero before export.

## Verification

The final deterministic test suite contains 36 passing tests. The real-data pipeline completed successfully and regenerated the scenario comparison, OpenDSS handoff, and metadata artifacts.

## Week 3 readiness

The optimizer-to-power-flow interface now has explicit columns, units, timezone, timestep, signs, and numerical tolerance. The project is ready to advance to Week 3: OpenDSS fundamentals.

## Recommended future improvements

These are optional and should not delay Week 3:

- add visual scenario-comparison plots;
- store source-file hashes in artifact metadata;
- add command-line arguments for scenario and carbon-weight selection;
- remove tracked cache files and operating-system metadata;
- expand README setup and execution instructions.