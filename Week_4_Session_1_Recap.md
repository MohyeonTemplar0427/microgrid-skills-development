# Week 4 Session 1 Recap - Per-Interval Electrical Feasibility

## Completion Status

Week 4 Session 1 is complete.

The externally controlled 15-minute QSTS replay now produces
machine-readable transformer, PCC, line-loading, violation, and
feasibility results for every dispatch interval.

## Implemented Fields

Each replay interval now includes:

- `transformer_apparent_power_kva`
- `transformer_loading_percent`
- `transformer_real_loss_kw`
- `pcc_grid_net_import_kw`
- `pcc_grid_import_kw`
- `pcc_grid_export_kw`
- `reverse_power_flow`
- `line_normal_rating_a`
- `line_loading_percent`
- `voltage_violation`
- `line_overload`
- `transformer_overload`
- `feasible`

The former `source_real_power_kw` field was renamed
`feeder_input_real_power_kw` because the feeder input is downstream
of the transformer and is no longer the utility-source measurement.

## Feasibility Definition

An interval is feasible when:

- The OpenDSS solution converges.
- Load-bus voltage remains within 0.95-1.05 pu.
- Maximum feeder current does not exceed the normal rating.
- Transformer loading does not exceed 100%.

Reverse power flow is reported independently. It is not automatically
classified as infeasible because the current model does not define a
no-export interconnection constraint.

## Representative Results

For the first combined-optimal interval:

- Maximum feeder current: 19.008793 A
- Feeder normal rating: 800 A
- Feeder loading: 2.376099%
- Transformer apparent power: 15.803743 kVA
- Transformer loading: 2.107166%
- Transformer real-power loss: 0.003330 kW
- Scheduled grid import: 15.000000 kW
- PCC net grid import: 15.006935 kW
- Reverse power flow: false
- Feasible: true

The difference between scheduled import and PCC import represents
feeder and transformer losses.

## Validation

- 57 automated tests passed.
- A normal QSTS interval was classified as feasible.
- Transformer and line loading percentages were independently checked.
- PCC import/export arithmetic and reverse-flow flags were checked.
- A deliberate 1000 kW interval triggered line and transformer
  overloads and was classified as infeasible.

Run the suite with:

```bash
/usr/local/bin/python3 -m pytest -q
```

## Remaining Week 4 Work

- Locate or generate all five required dispatch schedules.
- Replay no-battery, rule-based, cost-optimal, carbon-optimal, and
  combined-optimal scenarios through the same OpenDSS model.
- Aggregate voltage, line loading, transformer loading, losses,
  reverse flow, violations, and infeasible intervals by scenario.
- Save the interval and comparison reports as reproducible artifacts.
- Complete the Week 4 validation report and Gate C review.

## Optional Future Development

A future high-fidelity extension should represent the physical
behavior of every major grid component using equipment-specific data
and the appropriate simulation timescale. This could include:

- Battery electrothermal and aging behavior, including SOC, depth of
  discharge, C-rate, temperature, calendar aging, and potentially
  different charging and discharging degradation weights
- PV and battery inverter efficiency maps, kVA limits, reactive-power
  capability, temperature derating, and Volt-VAR or Volt-Watt control
- Transformer magnetizing current, no-load loss, tap settings,
  grounding, thermal loading, and tested winding impedance
- Utility-source short-circuit strength and X/R ratio
- Feeder conductor geometry, neutral and grounding impedance,
  capacitance, temperature-dependent resistance, and verified ampacity
- Voltage-dependent load composition, phase imbalance, motor behavior,
  and measured reactive power
- Protection, faults, harmonics, switching behavior, and fast
  electromagnetic transients where those phenomena affect the study

No single model resolves every physical timescale well. OpenDSS should
remain the distribution and QSTS model, while SPICE or an EMT tool can
represent converter switching and a separate electrothermal model can
represent detailed battery aging. These extensions are optional and
must not delay the required Week 4 scenario-validation work.

## Exact Next Step

Begin Week 4 Session 2 in `src/qsts_simulation.py` by identifying the
existing schedule artifacts and defining an explicit mapping from the
five required scenario names to their input files.
