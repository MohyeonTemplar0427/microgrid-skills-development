# Microgrid backend architecture

Reference for the time-series, surplus, metering and tariff layers. Covers the
conventions that are decisions rather than derivations — the things a reader
cannot recover from the code alone.

## Layer separation

| Layer | Package | Answers |
|---|---|---|
| Time series | `src/timeseries` | What are the inputs, on what grid, in what units? |
| Profiles | `src/profiles` | Where do load and PV come from? |
| Surplus | `src/surplus` | Where does excess PV go, and does it balance? |
| Metering | `src/billing/meter_topology.py` | Which flows are billed together? |
| Tariffs | `src/billing/tariffs.py` | What are the rates, and when were they valid? |
| Billing | `src/billing/charges.py` | What does it cost? |

The physical network (`src/opendss`) and the billing topology are deliberately
distinct. OpenDSS determines voltages, currents, losses and real PCC power.
Meter topology determines what appears on which bill. Two sites with identical
physics can bill very differently, so neither layer can be inferred from the
other.

## The normalized interval table

Required columns:

| Column | Units | Meaning |
|---|---|---|
| `timestamp` | tz-aware | **Start** of the interval |
| `native_load_kw` | kW | Site demand before PV and battery effects |
| `pv_available_kw` | kW | Maximum PV from sunlight, before curtailment |
| `price_per_kWh` | $/kWh | Import energy price |
| `carbon_intensity_g_per_kWh` | gCO₂/kWh | Grid carbon intensity |

Optional: `flexible_load_available_kw`, `export_limit_kw`,
`export_price_per_kWh`. Absent means the capability is *disabled*, which is not
the same as present-and-zero.

### Inclusive end date

The GUI takes an **inclusive** end date. Internally the horizon is half-open:

```
user picks   2026-06-01 .. 2026-06-03   (inclusive)
internal     2026-06-01 00:00 .. 2026-06-04 00:00   (start <= t < end)
```

The conversion advances one calendar day with `pd.DateOffset(days=1)`, **not**
`pd.Timedelta(days=1)`. Timedelta adds exactly 24 hours, which lands at 01:00
local on a daylight-saving day and silently drops or duplicates an hour.

### Interval counts are never assumed

A local day is not always 96 fifteen-minute intervals. Spring-forward days have
92 and fall-back days have 100. Every count comes from the generated index, and
`number_of_days * 96` appears nowhere.

### Missing data

`MissingDataPolicy` defaults to `REJECT`. Filling happens only under an
explicit policy, and the number of distinct timestamps filled in any input
column is recorded on the result so a filled interval is never presented as
measured.

## PV allocation: the PV-first convention

Within each interval, available PV is allocated in fixed priority order:

1. **Native load** — displaces grid import first, the highest-value use under
   any tariff with a positive import price.
2. **Battery charging** — surplus beyond native load, up to scheduled charge.
3. **Flexible load** — if enabled.
4. **Grid export** — if enabled, up to the limit.
5. **Curtailment** — whatever remains.

This is an **accounting** convention, not a claim about electrons. Real power
flow is set by the network; the convention decides how a kWh is *labelled* for
reporting "self-consumed PV" and "battery charging attributed to surplus PV".
It matters because battery charge can come from PV or the grid, and the split
is otherwise ambiguous. Under PV-first, charging is attributed to PV only up to
the PV remaining after native load; anything beyond is grid-charged.

The interval identity that always holds:

```
pv_available = pv_serving_native_load + pv_charging_battery
             + flexible_load_supplied + grid_export
             + pv_curtailed + losses
```

and the bus balance:

```
grid_import + pv_output + battery_discharge
  = native_load + flexible_load + battery_charge + grid_export
```

Both are enforced by `validate_power_balance`.

### Surplus capabilities coexist

Export, flexible load and curtailment are **not** four mutually exclusive
modes. A site can export up to a limit, divert some surplus to flexible load,
and curtail the rest, all in one interval. Curtailment has no enable flag: it
is always available and is the final feasibility mechanism, since not producing
power is always physically achievable.

Defaults are conservative: export **off**, flexible load **off**, remainder
**curtailed**.

### Simultaneity

Materially simultaneous grid import/export and battery charge/discharge are
rejected by `validate_no_simultaneity` within a kW tolerance. No mixed-integer
solver is introduced: with positive import prices and nonnegative export
compensation, simultaneity is economically dominated in a convex formulation,
so the schedule is *validated* rather than constrained with binaries.

## Tariffs are versioned data

A tariff carries an effective window, a source-document URL and a version
string. Lookups may be made for a date, and a lookup outside the effective
window raises rather than silently returning stale rates.

When rates change, **add a new definition** with its own effective window
rather than editing the numbers in place, so historical analyses stay
reproducible.

### PG&E B-10, effective 2026-03-01

Secondary voltage (below 2,400 V — the modelled 480 V service qualifies),
bundled service.

| Component | Value |
|---|---|
| Customer charge | $11.36882 per meter per day |
| Maximum demand | $20.50 per kW |

Summer (Jun 1 – Sep 30): peak 4–9 p.m. $0.33947; part-peak 2–4 p.m. and
9–11 p.m. $0.27778; off-peak $0.24522.

Winter (Oct 1 – May 31): peak 4–9 p.m. $0.26321; super off-peak 9 a.m.–2 p.m.
**in March, April and May only** $0.19139; other off-peak $0.22773.

Rates match on **local wall-clock hour**, so a 4 p.m. peak stays at 4 p.m.
local on both sides of a DST transition.

**B-19 is deliberately not implemented.** It uses several distinct demand
components — maximum plus separate peak-period and part-peak-period demand —
which cannot be approximated by B-10's single maximum-demand charge without
materially misstating cost in a way that would look plausible.

## Demand and customer charges

**Demand charges are never summed across intervals.** A demand charge bills the
single highest 15-minute average import per billing period, once. Summing
per-interval demand overstates cost by roughly the interval count, and is the
most common way this calculation goes wrong.

Billing periods are calendar months. A multi-month horizon gets a separate peak
*and* a separate customer charge per month.

For a partial billing cycle:

```
billed_peak = max(previous_peak, simulated_peak)
```

When the previous peak is unknown the simulated peak is used and the period is
flagged `is_partial_period` with a warning, because a real bill can only be
higher.

Customer charge:

```
customer_charge = daily_rate * billing_days * utility_account_count
```

`billing_days` counts local calendar service dates. It is not calculated as
elapsed hours divided by 24, because a daylight-saving date with 23 or 25 hours
is still one billing day.

Only **utility accounts** count. Submeters under a master meter allocate an
internal share and incur no separate customer or demand charge. A commercial
demand-metered schedule is never applied by default to residential unit meters:
a meter with no tariff and no explicit default raises rather than inheriting
one.

## Meter topologies

| Mode | Utility accounts | Demand measured at |
|---|---|---|
| `single_pcc` (default) | 1 | Aggregate PCC import |
| `master_with_submeters` | 1 | Master meter |
| `individual_meters` | one per unit | Each meter independently |
| `individual_with_shared_generation` | per unit + generation meter | Each meter independently |

Shared-generation allocation percentages must sum to 100% within tolerance, so
every generated kWh is credited exactly once. The allocation is a **billing
credit** — it does not assert that specific physical electrons reached a
specific unit.

Individually metered billing accepts a `meter_dispatches` table for every
utility account. Where per-unit load profiles are unavailable,
`individual_meters_topology` accepts
`uses_equal_allocation_approximation=True`, which records an explicit
`APPROXIMATION:` warning for display in Review and Run and in results. Without
either actual meter data or that explicit opt-in, billing raises instead of
silently splitting the PCC flow.

Shared-generation allocation percentages can be validated and energy can be
allocated for reporting, but utility billing for that topology deliberately
raises until an applicable NEM/NBT credit rule is configured. Equal division of
the PCC flow would not represent the separately metered accounts.

## Carbon-adjusted operating objective

The scenario comparison distinguishes physical emissions from their optional
monetary valuation:

```
monetized_carbon_cost = carbon_weight_$_per_kgCO2 * emissions_kgCO2
carbon_adjusted_operating_cost =
    total_explicit_operating_cost + monetized_carbon_cost
```

The primary results table shows emissions and the carbon-adjusted operating
cost. The standalone monetized component remains available in detailed data.
Objective values are comparable across strategies evaluated with the same
carbon weight; a carbon-weight sweep changes the scoring rule and should be
interpreted as a cost-versus-emissions tradeoff.

## Extension points (deliberately unimplemented)

These raise `NotImplementedError` with an explanation rather than returning
fabricated data, so no GUI control can silently produce invented numbers:

- `MeasuredLoadAdapter` — Green Button, Modbus, SunSpec, MQTT
- `WeatherDerivedPV` — configuration (location, tilt, azimuth, inverter
  efficiency, system losses) is validated and persistable, but no irradiance
  provider is connected
- `MeasuredInverterPV` — inverter telemetry reports *delivered* power;
  recovering *available* power additionally needs a curtailment signal or a
  clear-sky reference, which is an unresolved modelling decision
- `ExportCompensationMode.TARIFF` — NEM/NBT export rules are not modelled; use
  fixed or CSV export pricing

**Azimuth convention:** 0° north, 90° east, 180° south, 270° west.

## Backward compatibility

Legacy columns remain readable and writable:

| Legacy | Canonical |
|---|---|
| `load_kw` | `native_load_kw` |
| `pv_kw` | `pv_available_kw` |
| `gCO2/kWh` | `carbon_intensity_g_per_kWh` |
| `net_load_kw` | derived: `native_load_kw - pv_available_kw` |

`normalize_any_frame` accepts either schema. `to_legacy_columns` renders back.
Existing result CSVs in `results/` are unchanged, and their historical `week*`
filenames are retained.

The legacy `pv_kw` was ambiguous — available PV in inputs, delivered PV in
dispatch output. The canonical schema splits it into `pv_available_kw` and
`pv_output_kw`, which is what makes curtailment expressible at all.

## Future system-sizing extension

The current scope evaluates operation of an already-built microgrid. A future
system-sizing study may add battery and PV capital cost, installation cost,
inverter replacement, fixed maintenance, project lifetime, discount rate,
incentives, tax credits, and battery replacement schedules. Those lifecycle
cash flows are intentionally excluded from present operating-cost results.
