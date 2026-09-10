# Analysis backend

Backend helpers for the guided analysis workflow (Analysis Setup → Strategy
Setup → Microgrid Configuration → Review and Run → Results). This layer is
behaviour and validation only; it draws nothing.

## What the frontend calls

| Step | Function | Returns |
|---|---|---|
| Analysis Setup | `signal_pipeline.source_config.resolve_signal_config(mode, ...)` | `ResolvedSignalConfig` |
| Analysis Setup | `signal_pipeline.horizon.build_horizon(start_date, number_of_days, timezone, timestep_minutes)` | `AnalysisHorizon` |
| Strategy Setup | `analysis.carbon_weights.expand_carbon_weights(mode, ...)` | `tuple[float, ...]` |
| Strategy Setup | `analysis.carbon_weights.build_scenario_names(base, weights)` | `dict[str, float]` |
| Microgrid Config | `analysis.no_battery.battery_parameters_are_required(strategies)` | `bool` |
| Review and Run | `signal_pipeline.signal_loader.load_signal_data(config, horizon, ...)` | integrated `DataFrame` |
| Review and Run | `analysis.no_battery.create_no_battery_dispatch(signals)` | dispatch `DataFrame` |

## Source modes

`live_api` requires a region and resolves the market provider, market
location, carbon provider, carbon zone and timezone from the region preset.
Any of those five may be overridden; the result is validated and the registry
entry is never mutated.

`integrated_csv` requires **no** region, and uses no market provider, market
node or carbon zone. It still needs a **named** timezone, from either the user
or a tz-aware timestamp column. A bare UTC offset (including `Etc/GMT±N`) is
refused, because it cannot say when daylight-saving transitions occur. Plain
`UTC` is accepted, since it genuinely has none.

## Price modes

`wholesale_market`, `fixed_retail`, `time_of_use`, `csv`. See
[../signal_pipeline/README.md](../signal_pipeline/README.md) for the schedule
representation and the holiday limitation.

## Analysis horizon

`start <= timestamp < end`, timezone-aware, with the interval count read off
the generated index. The count is **never** `number_of_days * 96`: a
spring-forward local day holds 92 fifteen-minute intervals and a fall-back day
holds 100.

Note that `build_horizon` advances the end with `pd.DateOffset(days=n)`, not
`pd.Timedelta(days=n)`. Timedelta adds exactly 24 hours, which lands at 01:00
local on a transition day and silently produces the wrong window.

## No-battery contract

A no-battery run is the *absence* of storage, not a battery of size zero.
`create_no_battery_dispatch` takes no battery argument at all, so a
user-entered battery value has no path into the result. Every battery quantity
is pinned to zero: charge, discharge, net injection, throughput, equivalent
full cycles and degradation cost.

`Battery.__post_init__` requires positive capacity, positive power limits and
`0 < efficiency <= 1`. Those checks protect real battery runs and must not be
loosened to let a zero-capacity instance through.

### Remaining migration work

Two places still require a real battery, and both were left alone because
`src/simulation/time_series_analysis.py` — under concurrent edit — calls into
them:

1. **`src/dispatch/dispatch_scenarios.py`, `create_required_dispatch_scenarios`.**
   Takes `battery_parameters` as a positional argument even to build the
   `no_battery` scenario, derives that scenario from the *optimized*
   `combined_optimal` schedule (so a full optimization must run first), and
   then writes a fake state of charge:

   ```python
   # Replay interface requires SOC even for no-battery, so put in fake value
   no_battery["battery_soc_kWh"] = battery_parameters["initial_soc_kWh"]
   ```

   That value is user-entered battery state appearing in a no-battery result.

2. **`src/dispatch/dispatch_metrics.py`, `calculate_battery_usage_metrics`.**
   Computes `equivalent_full_cycles` as throughput divided by
   `max_soc_kWh - min_soc_kWh`. With no battery that denominator is zero, so
   the function cannot be called on a no-battery run at all — hence
   `no_battery.no_battery_usage_metrics()`, which returns the zeros directly.

**Proposed migration**, to run once the simulation layer is free:

- Add `battery: Battery | None` (or an explicit `battery_enabled: bool`) to
  the dispatch-scenario entry point, defaulting to the current behaviour.
- When it is `None`, build `no_battery` directly from the signal frame via
  `analysis.no_battery.create_no_battery_dispatch` instead of deriving it
  from an optimized schedule. This also removes the need to optimize before
  producing the baseline.
- Make `battery_soc_kWh` nullable in the replay interface, or drop the column
  for no-battery schedules, so the fake SOC assignment disappears.
- Guard `calculate_battery_usage_metrics` against a zero denominator and have
  it raise, rather than return a misleading zero — callers with no battery
  should use `no_battery_usage_metrics()`.
- Do not relax any `Battery` validation as part of this.

## Deferred: load and PV profile modelling

Ratings are **not** inferred from time-series maxima, and no automatic scaling
is implemented. These contracts are open and need a decision from the frontend
team before any inference is added:

1. **What PV data represents.** Actual AC kW at the meter, plane-of-array
   irradiance (W/m²), or a unitless capacity factor (0–1). Each implies a
   different conversion, and a profile whose peak happens to look like a kW
   rating is indistinguishable from a capacity factor scaled by that rating.
2. **How PV scales with configured capacity.** Whether a configured DC kW
   multiplies a normalized profile, whether a DC/AC ratio and inverter
   clipping apply, and whether the profile is assumed already clipped.
3. **What load configuration means.** Constant demand, annual peak demand to
   scale a normalized shape against, or an absolute measured series that
   should not be scaled at all.
4. **Missing profile intervals.** Whether to reject the run, interpolate
   short gaps, or carry the previous value forward — and what gap length
   separates those. The current behaviour is to reject: `align_to_horizon`
   raises `MissingIntervalError` rather than filling anything, because a
   silently interpolated load directly biases both cost and emissions.

Until these are settled, load and PV must arrive as explicit `load_kw` and
`pv_kw` columns already in kW. They are always **site profile inputs**: a
regional market API prices a node and a carbon API reports a zone, and neither
knows anything about one site's consumption or generation.
