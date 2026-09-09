# Week 4 Completion Recap - Microgrid QSTS Validation

## Purpose and Completion Status

Week 4 is complete for the current model scope.

The project now connects two layers that answer different engineering
questions:

- Dispatch optimization determines how the battery should operate.
- OpenDSS determines whether that schedule is electrically acceptable
  when applied to the modeled microgrid.

Five dispatch strategies can be evaluated with the same time-series
signals and physical network. The workflow produces interval-level
electrical results, scenario summaries, and a machine-readable
completion checklist. The complete automated suite passed 66 tests.

## Physical Microgrid Model

The modeled power path is:

```text
Utility grid
    |
12.47 kV point of common coupling (PCC)
    |
750 kVA delta-grounded-wye service transformer
    |
0.48 kV service bus
    |
Low-voltage feeder
    |
0.48 kV load bus
    |-- Building load
    |-- Rooftop PV system
    `-- Battery energy-storage system
```

The PCC is the accounting boundary between the utility and the
microgrid. Positive PCC real power represents grid import. Negative
PCC real power represents export, also called reverse power flow.

The service transformer changes voltage and introduces real and
reactive losses. Its loading is evaluated using apparent power, because
both real power and reactive power use transformer capacity:

```text
S = sqrt(P^2 + Q^2)
transformer loading (%) = S / transformer rating * 100
```

The feeder introduces voltage drop and conductor loss. Conductor loss
is related to current approximately by `I^2 R`, so a higher-current
operating point can increase loss nonlinearly. Feeder loading is the
maximum phase current divided by the normal ampere rating.

The building is presently represented as a balanced, three-phase,
constant-power load. The PV and battery are connected to the load bus
through simplified OpenDSS inverter models. The battery follows an
externally calculated charge or discharge command.

The values above describe the current representative circuit, not a
universal microgrid. Operating schedules can be varied without changing
the circuit. Changing equipment ratings, impedance, topology, or control
settings creates a different physical design case and may materially
change the conclusions.

## External Signals, Control, and Physics

The workflow deliberately separates three types of information:

```text
External conditions
    load, available PV, price, grid carbon intensity
                         |
                         v
Control decision
    battery charge/discharge schedule and SOC trajectory
                         |
                         v
Physical evaluation
    voltage, current, equipment loading, losses, PCC flow, feasibility
```

Price and grid carbon intensity are external signals. The carbon weight
is an economic preference used by the optimizer; it is not a physical
property of the microgrid. Battery size, power limits, efficiencies,
SOC limits, transformer rating, feeder impedance, and inverter ratings
are internal model parameters.

This separation allows many operating datasets and control strategies
to be compared against one fixed network. It also supports a different
study type in which physical parameters are varied deliberately for
equipment sizing or sensitivity analysis.

## Dispatch Scenarios

The required scenarios are:

- `no_battery`: establishes the electrical baseline with zero battery
  injection.
- `rule_based`: follows explicit price- or carbon-threshold logic.
- `cost_optimal`: minimizes grid-energy cost and can include battery
  throughput degradation cost.
- `carbon_optimal`: minimizes emissions associated with grid import.
- `combined_optimal`: minimizes energy cost, weighted carbon emissions,
  and battery degradation cost together.

All strategies use a common timestamp, load, PV, price, and carbon
signal baseline. This controlled comparison attributes differences to
dispatch rather than to different external conditions.

Battery throughput is the sum of charge and discharge energy. The
current degradation model applies one linear cost per kWh of throughput.
Equivalent full cycles normalize throughput by twice the usable battery
capacity. This is an operational approximation, not a detailed physical
aging model.

## QSTS Replay

Replay means applying a previously calculated dispatch schedule to
OpenDSS one interval at a time. For every 15-minute record, the workflow:

1. Sets the building real-power demand.
2. Converts scheduled PV power into OpenDSS irradiance.
3. Sets battery SOC, operating state, and charge/discharge power.
4. Solves a steady-state power flow.
5. Records electrical quantities and constraint flags.
6. Advances to the next dispatch record.

This is an externally controlled quasi-static time-series (QSTS)
simulation. Each interval is a settled steady-state operating point.
The model does not resolve inverter switching, fault transients, or the
sub-second transition between intervals.

The scheduled grid value represents the optimizer's power balance. The
PCC value is calculated by OpenDSS and includes the physical losses of
the feeder and transformer, so the two values are not expected to be
identical.

## Reverse Power Flow

Normal power direction is from the utility through the transformer to
the microgrid. Reverse power flow occurs when local generation and
battery discharge exceed load, battery charging, and internal losses,
causing net real power to flow from the microgrid to the utility.

Reverse flow is reported independently from feasibility. It is not
automatically a violation because the current model has no zero-export
interconnection constraint. A future project with a no-export agreement
should add export magnitude or reverse-flow status to the feasibility
definition.

## Electrical Feasibility

An interval is feasible when all of the following are true:

- The OpenDSS solution converges.
- Load-bus voltage remains between 0.95 and 1.05 pu.
- Feeder loading does not exceed its normal rating.
- Transformer loading does not exceed 100%.

The interval output separately records voltage violation, line
overload, transformer overload, reverse flow, and overall feasibility.
Keeping the individual flags makes the cause of an infeasible interval
traceable.

## Function Roles

### Dispatch creation and shared metrics

| Function | Role |
|---|---|
| `run_rule_based_dispatch()` | Applies explicit threshold-based battery control. |
| `run_cost_optimization()` | Finds a cost-minimizing schedule with optional degradation cost. |
| `run_carbon_optimization()` | Finds a grid-emissions-minimizing schedule. |
| `run_combined_optimization()` | Trades off energy cost, carbon cost, and degradation cost. |
| `calculate_dispatch_metrics()` | Totals grid-import energy, energy cost, and emissions over any horizon. |
| `calculate_battery_usage_metrics()` | Totals charge, discharge, throughput, and equivalent full cycles. |
| `create_optimized_dispatch_scenarios()` | Runs the four battery-control strategies from one common dataset. |
| `create_required_dispatch_scenarios()` | Adds the no-battery baseline and converts every schedule to the OpenDSS handoff schema. |
| `save_required_dispatch_scenarios()` | Saves the five standardized dispatch files. |
| `scenario_generation.main()` | Fetches or loads the common signals and runs the complete scenario-generation workflow. |

The two metric functions live in `src/dispatch/dispatch_metrics.py` because their
calculations are independent of whether the horizon is one day, several
days, or a longer study.

### OpenDSS circuit and interval physics

| Function | Role |
|---|---|
| `create_base_circuit()` | Clears OpenDSS and creates the source, PCC, transformer, feeder, and building load. |
| `add_replay_resources()` | Adds the simplified rooftop PV and battery elements. |
| `apply_dispatch_operating_point()` | Applies one schedule row to the load, PV, and battery, then solves the circuit. |
| `calculate_feeder_metrics()` | Reads feeder phase currents, power flow, apparent power, power factor, and losses. |
| `calculate_transformer_metrics()` | Reads transformer input power, loading, and losses. |
| `calculate_pcc_metrics()` | Converts transformer input power into PCC import, export, and reverse-flow status. |
| `classify_line_loading()` | Classifies current as normal, emergency, or above emergency rating. |
| `assess_line_loading()` | Calculates maximum current and loading percentages from phase currents. |
| `assess_voltage_limits()` | Compares phase voltage magnitudes with the permitted per-unit range. |
| `replay_dispatch_timeseries()` | Repeats operating-point application and measurement for the full schedule. |

### Scenario replay and aggregation

| Function | Role |
|---|---|
| `create_no_battery_replay_schedule()` | Removes battery operation to create a counterfactual baseline. |
| `create_qsts_scenario_comparison()` | Aggregates interval results into comparable electrical scenario metrics. |
| `load_required_dispatch_scenarios()` | Loads all five schedules from the explicit filename map. |
| `replay_required_dispatch_scenarios()` | Sends every loaded schedule through the same OpenDSS replay. |
| `run_required_qsts_analysis()` | Coordinates loading, replay, and electrical comparison. |
| `save_required_qsts_results()` | Saves each interval-level replay and the scenario comparison. |
| `qsts_simulation.main()` | Runs the complete five-scenario QSTS workflow. |

### Final validation

| Function | Role |
|---|---|
| `create_dispatch_performance_summary()` | Aligns schedules with price and carbon signals and calculates operational KPIs. |
| `create_validation_report()` | Joins operational KPIs with OpenDSS electrical outcomes by scenario. |
| `build_validation_report()` | Loads the saved inputs and builds the combined report. |
| `create_opendss_validation_checklist()` | Summarizes the evidence required by the curriculum completion gate. |
| `save_validation_artifacts()` | Saves the final combined report and completion checklist. |
| `validation.main()` | Runs, checks, prints, and saves the final validation workflow. |

## Reusable Outputs

The workflow saves four levels of evidence:

- Common external-signal inputs
- Five standardized dispatch schedules
- Five interval-level OpenDSS replay files and one electrical comparison
- One combined validation report and one completion checklist

The raw CSV files retain case-specific results without embedding a
single dataset's complete numerical table in this recap. Regenerating
the files after changing valid input parameters allows the same report
structure to describe a different case.

Important final artifacts are:

```text
results/week4_qsts_scenario_comparison.csv
results/week4_final_validation_report.csv
results/week4_opendss_validation_checklist.csv
```

## Model Boundaries and Future Development

The optimization battery parameters are configurable, but many OpenDSS
equipment values are currently embedded in circuit command strings.
Changing optimizer capacity or PV size does not yet automatically update
the corresponding OpenDSS element. A shared `MicrogridConfig` should
eventually provide one source of truth for both layers.

Physical extensions may include:

- Equipment-specific transformer loss, impedance, tap, grounding, and
  thermal data
- Feeder conductor geometry, neutral impedance, capacitance,
  temperature-dependent resistance, and verified ampacity
- Unbalanced and voltage-dependent load models
- PV and battery inverter efficiency maps, kVA limits, reactive-power
  capability, derating, and Volt-VAR or Volt-Watt control
- Battery SOC-, temperature-, C-rate-, calendar-, and depth-of-discharge
  dependent aging
- Utility short-circuit strength, protection coordination, faults,
  harmonics, switching, and electromagnetic transients
- Configurable export limits and interconnection rules

OpenDSS remains appropriate for distribution power flow and QSTS.
Dedicated dynamic, EMT, or electrothermal tools may be needed for faster
or more detailed physical behavior.

## Validation and Completion

The automated suite passed 66 tests. The final checklist confirms that
the base feeder, five-scenario replay, convergence, voltage, loading,
loss, reverse-flow, infeasibility, machine-readable feasibility, and
solution-mode documentation requirements are present.

This completion statement is conditional on the current circuit,
assumptions, and tested datasets. It shows that the workflow is
traceable and reusable; it does not claim that every possible physical
configuration or operating dataset will be feasible.

Run the principal workflows with:

```bash
/usr/local/bin/python3 -m src.dispatch.scenario_generation
/usr/local/bin/python3 -m src.opendss.qsts_simulation
/usr/local/bin/python3 -m src.opendss.validation
/usr/local/bin/python3 -m pytest -q
```

Revised Week 4 and Gate C are complete. The project may proceed to the
revised Week 5 SQL curriculum.
