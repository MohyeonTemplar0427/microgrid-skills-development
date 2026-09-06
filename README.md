# Session_Week1
Repo for creating knowledge framework for energy engineer. 

## Current curriculum status

Revised Weeks 3 and 4 are complete, and Gate C has passed for the
current model scope and two-day real-signal dataset.

The validated workflow now includes:

- A 12.47 kV PCC, 750 kVA service transformer, 0.48 kV feeder,
  building load, rooftop PV, and externally dispatched battery
- Five common-input dispatch scenarios: no battery, rule based,
  cost optimal, carbon optimal, and combined optimal
- 15-minute QSTS replay through the same OpenDSS model
- Per-interval voltage, line loading, transformer loading, loss,
  reverse-flow, violation, and feasibility results
- A combined operational and electrical validation report
- A machine-readable OpenDSS completion checklist

All 960 Week 4 interval solutions converged and were feasible. The
complete automated suite passed with 66 tests.

Run the final Week 4 validation workflow:

```bash
/usr/local/bin/python3 -m src.week4_validation
```

Run the complete test suite:

```bash
/usr/local/bin/python3 -m pytest -q
```

Completion evidence:

- [`Week_3_Completion_Recap.md`](Week_3_Completion_Recap.md)
- [`Week_4_Completion_Recap.md`](Week_4_Completion_Recap.md)
- `results/week4_final_validation_report.csv`
- `results/week4_opendss_validation_checklist.csv`

The project is ready to begin revised Week 5 SQL work.


## Week 2: Real-data consolidation

Week 2 completed strict time-series validation, one-to-one signal alignment, real CAISO price and Electricity Maps carbon scenarios, degradation-aware common-baseline comparisons, and a validated OpenDSS handoff.

Run the deterministic tests:

```bash
pytest -q
```

Run the real-data experiment:

```bash
python3 src/market_data_integration.py
```

Generated artifacts:

- `results/week2_market_signal_scenario_comparison.csv`
- `results/week2_opendss_handoff_combined_real_15min.csv`
- `results/week2_opendss_handoff_combined_real_15min_metadata.json`

See [`Week_2_Completion_Recap.md`](Week_2_Completion_Recap.md) for results, validation rules, units, sign conventions, limitations, and Week 3 readiness.

## Future Development: Dynamic and Transient Analysis

Dynamic and transient electrical analysis are **not currently implemented** in this repository. The current OpenDSS workflow uses 15-minute quasi-static time-series (QSTS) simulation: each interval is solved as a separate steady-state power flow to evaluate settled voltage, current, equipment loading, and losses once the network has reached a new operating point.

### Why QSTS is appropriate today

- The dispatch schedule that drives the simulation operates on 15-minute intervals, so there is no need to resolve behavior faster than that.
- Most electromagnetic transients (switching surges, fault current spikes, controller response) settle in milliseconds to a few seconds — far shorter than one 15-minute interval.
- The current engineering objective is to characterize sustained operating conditions (voltage profiles, loading, losses) across a full schedule, not sub-second behavior.
- Using QSTS is a scoping choice, not a claim that transient responses do not occur. Transients happen between the snapshots QSTS solves; they are simply outside the current analysis boundary.

### Proposed future workflow

1. Run QSTS across the complete operating schedule, as is done today.
2. Identify critical intervals from the QSTS results, including maximum charging, maximum discharging, minimum voltage, and maximum equipment loading.
3. Use the solved network state from each critical interval as the initial condition for a dynamic or transient study.
4. Apply an event of interest at that initial condition, such as a fault, an inverter trip, a sudden load change, a switching event, or a grid disconnection.
5. Evaluate the response: current peaks, voltage recovery, protection timing, stability, and inverter ride-through behavior.
6. Feed any operational restrictions discovered during transient evaluation back into the dispatch optimizer, so the schedule respects limits that QSTS alone cannot reveal.

### Steady-state realism improvements (QSTS model)

The following data would improve the realism of the existing QSTS model and are worth incorporating before or alongside any transient work:

- Line resistance, reactance, length, and ampacity
- Transformer voltage ratio, impedance, and kVA rating
- Load real power, reactive power, and power factor
- PV inverter kVA and reactive-power capability
- Battery inverter kVA, charge/discharge limits, and reactive-power capability
- Bus-voltage limits
- Equipment-loading limits
- Explicit load, PV, and battery sign conventions

### Data required for future transient studies

- Protection curves and clearing times
- Fault type, location, and impedance
- Inverter current limits and controller parameters
- PLL and inner-control behavior
- Voltage/frequency ride-through settings
- Trip and reconnection timing
- Transformer saturation and inrush data
- Motor inertia and dynamic-load models
- Subsecond input and measurement profiles

Unverified placeholder parameters should not be presented as realistic system data. Any parameters used for future dynamic or transient work should come from manufacturer documentation, utility data, applicable standards, or clearly identified engineering assumptions.

OpenDSS itself supports fault studies, harmonic analysis, duty-cycle studies, and basic dynamics. Detailed electromagnetic-transient (EMT) studies, however, may require a dedicated EMT tool.
