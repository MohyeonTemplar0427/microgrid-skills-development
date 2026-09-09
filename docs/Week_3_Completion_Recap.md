# Revised Week 3 Completion Recap - OpenDSS Fundamentals

## Completion Status

Revised Week 3 is complete.

The project now contains a documented and tested radial distribution
model with a point of common coupling, distribution transformer,
low-voltage service feeder, building load, PV location, and storage
location.

Final validation:

- 56 automated tests passed.
- The base power flow converged.
- Load-bus voltage remained within the 0.95-1.05 pu range.
- The service feeder remained below its normal current rating.
- The service transformer remained below its kVA rating.
- PCC import and export signs were verified.
- Snapshot and Daily solution modes were demonstrated.

## Circuit Topology

The revised feeder contains:

1. A 12.47 kV utility source.
2. `pcc_bus`, the point of common coupling.
3. `Transformer.ServiceTransformer`.
4. `service_bus` at 0.48 kV.
5. `Line.Feeder` between the service and load buses.
6. `load_bus` at 0.48 kV.
7. The building load, rooftop PV, and battery location.

The one-line diagram is documented in
`Week_3_One_Line_Diagram.md`.

## Transformer Model

The service transformer uses:

- Three phases
- Two windings
- Primary voltage: 12.47 kV
- Secondary voltage: 0.48 kV
- Primary connection: delta
- Secondary connection: grounded wye
- Rating: 750 kVA
- Resistance: 0.5% per winding
- Leakage reactance: 5.75%

The 500 kW building load at 0.95 power factor requires approximately:

$$
S = \frac{500\text{ kW}}{0.95} = 526.3\text{ kVA}
$$

The 750 kVA rating therefore provides capacity above the nominal load.

## Low-Voltage Service Feeder

Moving the building from 12.47 kV to 0.48 kV increases current
substantially. The low-voltage feeder was therefore revised to use:

- Length: 0.1 km
- Positive-sequence resistance: 0.02 ohm/km
- Positive-sequence reactance: 0.04 ohm/km
- Zero-sequence resistance: 0.04 ohm/km
- Zero-sequence reactance: 0.08 ohm/km
- Normal rating: 800 A
- Emergency rating: 1000 A

These values replace the former 1 km, 100 A medium-voltage feeder
assumption.

## Base-Case Results

With the building at 500 kW and 0.95 power factor, the revised base
case produced approximately:

| Metric | Result |
|---|---:|
| Load-bus voltage | 0.9716 pu |
| Maximum feeder current | 651.4 A |
| Feeder normal loading | 81.4% |
| Feeder real-power loss | 2.55 kW |
| Transformer apparent power | 541.5 kVA |
| Transformer loading | 72.2% |
| Transformer real-power loss | 3.91 kW |
| PCC net grid import | 506.4 kW |
| Reverse power flow | No |

The base case satisfies the defined voltage, line-loading, and
transformer-loading limits.

## Point of Common Coupling

The PCC is `pcc_bus`, located at the transformer primary.

Transformer terminal-1 power therefore represents utility exchange:

- Positive real power means grid import.
- Negative real power means grid export.
- Negative net import is classified as reverse power flow.

Focused tests verify both the normal import case and a deliberate PV
export case.

## Solution Modes

The base feeder explicitly selects OpenDSS Snapshot mode. Snapshot
solves one steady-state operating point and is reported by
OpenDSSDirect as mode `0`.

Daily mode was demonstrated with four 15-minute steps. OpenDSS
advanced from hour 0 to hour 1 and remained converged. Daily mode is
reported as mode `1`.

The existing Python QSTS workflow is an externally controlled sequence
of Snapshot solutions. Python applies each dispatch row, while
OpenDSS solves the corresponding electrical operating point.

Further details are documented in
`Week_3_OpenDSS_Solution_Modes.md`.

## Software and Testing

Week 3 added or updated:

- Immutable transformer and PCC result dataclasses
- Transformer power, loading, and loss calculation
- PCC import, export, and reverse-flow calculation
- Explicit Snapshot-mode configuration
- Transformer and low-voltage resource modeling
- Focused numerical tests
- Import and export sign tests
- Integrated base-case electrical acceptance test
- Command-line transformer and PCC reporting

Run the complete suite with:

```bash
/usr/local/bin/python3 -m pytest -q
```

Run the focused base analysis with:

```bash
/usr/local/bin/python3 -m src.opendss_analysis
```

## Current Modeling Assumptions

- The circuit is balanced and three-phase.
- The building load uses a fixed 0.95 power factor.
- PV and storage operate at unity power factor.
- PV and storage connect at the 0.48 kV load bus.
- Detailed inverter-efficiency and temperature curves are omitted.
- Battery SOC is prescribed by Python during dispatch replay.
- OpenDSS does not independently integrate battery SOC.
- Protection, harmonics, and electromagnetic transients are outside
  the present scope.

## Future Model Improvements

Future development should replace representative electrical values
with equipment-specific parameters derived from utility data,
nameplates, datasheets, or field measurements. Important additions
include:

- Utility-source short-circuit strength and X/R ratio
- Transformer no-load loss, magnetizing current, taps, grounding,
  and tested winding impedance
- Feeder conductor type, ampacity, phase spacing, neutral impedance,
  capacitance, and actual route length
- Grounding-electrode and neutral connections
- Voltage-dependent ZIP load behavior and measured reactive power
- PV-inverter and battery-inverter efficiency curves, reactive-power
  capability, temperature derating, and control settings
- Verified normal and emergency equipment ratings

These parameters would improve voltage-drop, loss, loading, fault,
and DER-response accuracy. They are deferred until suitable source
data are available and are not required to close revised Week 3.

## Week 4 Readiness

Revised Week 3 is complete, but Gate C remains open until Week 4 is
complete.

Week 4 must replay and compare:

- No battery
- Rule-based dispatch
- Cost-optimal dispatch
- Carbon-optimal dispatch
- Combined optimal dispatch

Each scenario must report voltage, line loading, transformer loading,
losses, reverse power flow, constraint violations, and infeasible
intervals in a machine-readable format.

## Subsequent Status Update

Week 4 Sessions 1-3 completed the work listed above. All five required
scenarios were replayed through the same OpenDSS model, all 960
interval solutions converged and were feasible, and the final
machine-readable validation checklist passed every requirement.

Gate C is now complete for the current model scope and dataset. See
`Week_4_Completion_Recap.md` and
`results/week4_opendss_validation_checklist.csv` for the final evidence.
