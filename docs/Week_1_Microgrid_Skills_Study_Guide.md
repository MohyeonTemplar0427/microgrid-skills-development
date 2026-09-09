# Week 1 Microgrid Skills Development — Study Guide

## Purpose of Week 1

Week 1 built a complete small-scale energy analytics workflow around a grid-connected microgrid with load, photovoltaic (PV) generation, and battery storage. The key achievement was not any single function or plot. It was learning how the physical model, time-series data, control logic, mathematical optimization, external grid data, performance metrics, software structure, and tests fit together.

The central engineering question was:

> Given time-varying load, PV generation, electricity price, and grid carbon intensity, how should a battery charge and discharge while respecting its physical limits?

Different answers are possible because “best” depends on the objective. A controller may minimize electricity cost, reduce emissions, increase self-consumption of PV, or balance several goals. Week 1 established the tools needed to model these choices and compare them fairly.

---

## 1. Battery Modeling: Turning Hardware into State Equations

A battery is an energy storage device, so its most important internal variable is stored energy. This is often expressed directly in kilowatt-hours (kWh) or as state of charge (SOC), the fraction of usable capacity currently stored.

For a battery with usable energy capacity:

> **State of charge = stored battery energy ÷ usable battery capacity**

In symbols: `SOC(t) = E(t) / E_max`

Here, `E(t)` is the energy stored at the current timestep, and `E_max` is the battery's usable capacity. For example, a battery holding 5 kWh with 10 kWh of usable capacity is at 50% SOC.

The battery cannot be modeled as an unlimited source or sink. A useful model includes:

- energy capacity in kWh;
- minimum and maximum SOC;
- maximum charging and discharging power in kW;
- charging and discharging efficiencies;
- the duration of each timestep;
- an initial SOC, and sometimes a required terminal SOC.

The stored-energy update is:

> **New stored energy = old stored energy + energy successfully charged − energy removed to support discharge**

In symbols:

`E(next) = E(now) + [charge efficiency × charge power × timestep] − [(discharge power × timestep) / discharge efficiency]`

For example, charging at 4 kW for 15 minutes with 90% efficiency adds `4 kW × 0.25 h × 0.90 = 0.90 kWh` to the battery.

Efficiency belongs inside the state equation because power crossing the external battery boundary is not identical to energy added to or removed from the cells. If the model ignores this distinction, it can create or destroy energy numerically.

Power and energy must also be kept conceptually separate. Power is an instantaneous rate measured in kW; energy is accumulated over time and measured in kWh. At 15-minute resolution, the timestep is 0.25 hours, so 4 kW maintained for one interval transfers `4 kW × 0.25 h = 1 kWh` before losses.

### Power balance

Every timestep must satisfy conservation of energy. Using nonnegative charge and discharge variables, a common grid-import convention is:

> **Grid power = load power − PV power + battery charging power − battery discharging power**

In symbols: `P_grid(t) = P_load(t) − P_PV(t) + P_charge(t) − P_discharge(t)`

Charging increases grid demand unless it uses otherwise-exported PV. Discharging reduces grid demand. A consistent sign convention is essential: many apparent optimization or plotting bugs are actually sign errors.

The battery model therefore acts as the physical contract for every controller. A rule-based strategy and an optimizer may make different decisions, but both must obey the same state update, bounds, and power balance.

---

## 2. Pandas Time Series: Giving the Model a Reliable Clock

Microgrid operation is sequential. The SOC at one time depends on all earlier charge and discharge decisions, so timestamps are part of the model rather than decorative labels.

The Week 1 daily dataset used 15-minute intervals. A full day therefore contains:

> **24 hours × 4 intervals per hour = 96 rows**

Typical columns included load, PV, electricity price, and carbon intensity. Pandas provided the structure for parsing timestamps, indexing rows by time, aligning signals, calculating derived columns, grouping results, and plotting trends.

A dependable time-series workflow checks that:

- timestamps are valid and ordered;
- the timezone is explicit;
- the expected interval is 15 minutes;
- values use consistent units;
- required signals line up on the same timestamps;
- missing or duplicated observations do not silently distort a simulation.

Timezone awareness matters when combining sources. A price reported in California local time and a carbon value reported in UTC cannot be joined safely by matching clock labels alone. Both series must represent the same actual instant. Daylight-saving transitions also mean that a local calendar day does not always contain exactly 96 quarter-hour intervals, so the assumed operating horizon must be stated clearly.

Pandas also makes vectorized calculations possible. For example, interval grid energy can be calculated from grid power as:

> **Grid energy for an interval = grid power × interval duration**

In symbols: `E_grid(t) = P_grid(t) × timestep_hours`

Cost and emissions then become interval energy multiplied by the corresponding price or carbon factor. Explicit units remain critical: a price in dollars per megawatt-hour must be converted before multiplying by kilowatt-hours, and carbon intensity units must match the energy unit used.

---

## 3. Rule-Based Dispatch: Encoding Operational Judgment

A rule-based controller uses explicit conditions to decide what the battery should do. Examples include charging during low-price periods, discharging during high-price periods, charging when carbon intensity is low, or discharging when carbon intensity is high.

At each timestep, the controller follows a sequence:

1. Observe the current signals and battery state.
2. Determine a desired action from the rule.
3. Limit that action by charge/discharge power ratings.
4. Limit it again by the available energy headroom or stored energy.
5. Apply efficiency and update SOC.
6. Calculate the resulting grid exchange.

This distinction between a desired action and a feasible action is fundamental. A rule may request full-power discharge, but an almost-empty battery cannot provide it for the whole interval. Similarly, excess PV cannot charge a battery that is already at its maximum SOC.

Rule-based dispatch is valuable because it is transparent and easy to debug. An engineer can explain exactly why a decision occurred. Its limitation is that it is usually myopic: it reacts to current conditions without perfectly accounting for later opportunities. For example, charging at a moderately low price now may fill the battery and prevent charging during an even cheaper period later.

Price-based and carbon-based rules can produce different schedules. A low-cost hour is not necessarily a low-carbon hour. This establishes an important Week 1 theme: economic and environmental objectives must be measured separately rather than assumed to agree.

---

## 4. CVXPY Optimization: Choosing an Entire Schedule at Once

Optimization replaces a sequence of hand-written control decisions with a mathematical problem. The optimizer considers the full time horizon and selects the charge and discharge schedule that minimizes an objective while satisfying constraints.

The main decision variables are usually charging power, discharging power, grid power, and battery energy or SOC at each timestep. Constraints encode the physical model:

- battery energy update across consecutive intervals;
- lower and upper SOC bounds;
- charge and discharge power limits;
- grid power balance;
- initial SOC;
- optional terminal SOC or grid-import/export limits.

For cost minimization, the objective is:

> **Choose the schedule that makes total electricity cost as small as possible.**

`Total cost = sum, over every timestep, of:`

`grid power × timestep duration × electricity price`

The price must first be converted into units compatible with grid energy. For emissions minimization, the objective is:

> **Choose the schedule that makes total grid-related emissions as small as possible.**

`Total emissions = sum, over every timestep, of:`

`grid power × timestep duration × grid carbon intensity`

CVXPY lets the model be written close to this mathematical form. The solver then finds a feasible schedule with the best objective value it can establish. This does not remove the engineer from the loop. The answer is only meaningful if the variables, units, boundary conditions, constraints, and objective represent the real problem correctly.

Several validation questions remain important after a solver reports success:

- Does SOC stay inside its limits?
- Does power balance close at every timestep?
- Are power and energy units consistent?
- Does the schedule exploit recognizable low-price or low-carbon periods?
- Is the terminal battery state fair for comparison with other strategies?

Optimization provides foresight, but it can also exploit omissions. If battery cycling has no cost and final SOC is unconstrained, the result may consume stored energy near the end simply because the model assigns no value to leaving energy in the battery.

---

## 5. Degradation and Equivalent Full Cycles

Battery operation has a physical cost: cycling contributes to degradation. A dispatch strategy that looks excellent on an electricity bill may be less attractive if it creates excessive throughput for a small benefit.

Energy throughput measures the total energy moved through the battery. Equivalent full cycles (EFC) translate partial charge/discharge activity into an intuitive normalized measure. One common convention based on total absolute cell-energy movement is:

> **Equivalent full cycles = (charge throughput + discharge throughput) ÷ (2 × usable battery capacity)**

In symbols: `EFC = (charged kWh + discharged kWh) / (2 × usable capacity in kWh)`

Example: if a 10 kWh usable battery charges by 10 kWh and later discharges by 10 kWh, then `EFC = (10 + 10) / (2 × 10) = 1 full cycle`.

Under this convention, charging through the full usable range and then discharging through it equals approximately one full cycle. Another valid convention uses discharge throughput alone. The important practice is to document which definition is used and apply it consistently.

EFC is a proxy rather than a complete electrochemical aging model. Actual degradation also depends on temperature, depth of discharge, C-rate, calendar age, average SOC, and cell chemistry. Still, EFC is useful for comparing strategies because it reveals when savings or emissions reductions are being purchased with substantially more battery use.

A simple degradation penalty can assign a monetary cost to throughput and add it to an optimization objective. Conceptually, this asks the optimizer to cycle only when the operational benefit exceeds the assumed wear cost.

---

## 6. Multi-Day Optimization and Boundary Conditions

Extending the horizon from one day to several days changes the problem in an important way: energy can be shifted across midnight. The optimizer may save energy late today for a high-value event tomorrow or charge today in anticipation of tomorrow's conditions.

The battery state equation must remain continuous across the entire horizon. Resetting SOC at each day boundary would create artificial energy and turn a multi-day study into unrelated daily simulations.

Initial and terminal SOC deserve special attention:

- **Initial SOC** specifies the energy available before the first decision.
- **Fixed terminal SOC** requires the study to return the battery to a chosen state.
- **Minimum terminal SOC** preserves a reserve without requiring an exact endpoint.
- **Free terminal SOC** allows maximum horizon value but can make comparisons unfair.

The “end effect” occurs when an optimizer drains the battery near the final timestep because no future period exists in the model. A terminal condition or terminal energy value can reduce this artifact. For fair scenario comparisons, strategies should normally begin with the same SOC and use compatible terminal assumptions.

Multi-day results can be summarized by day, but the optimization itself should retain chronological continuity. Daily summaries are views of one connected trajectory, not independent physical systems.

---

## 7. CAISO and Electricity Maps: Connecting to Real Grid Signals

External data turns a synthetic exercise into a grid-aware analysis. CAISO data can provide California market or system information, while Electricity Maps can provide location- and time-dependent carbon intensity.

An API integration generally involves:

1. constructing a request with the correct endpoint and parameters;
2. authenticating if required;
3. checking the response status;
4. parsing JSON, CSV, or another returned format;
5. converting timestamps and units;
6. mapping the data into a consistent pandas schema;
7. validating coverage and missing values;
8. preserving enough metadata to reproduce the dataset.

The most difficult part is often not downloading the data but establishing semantic consistency. A price series must have a known market, node or zone, interval, and unit. A carbon series must be identified as average or marginal intensity, and as historical, forecast, or real-time data. These distinctions change the meaning of the optimization.

Reusable experiments should not depend on a live API returning the same values forever. Saving a validated input snapshot allows tests and comparisons to be reproduced. Credentials belong outside source code, and data-fetching failures should be reported explicitly rather than silently replaced with plausible-looking values.

---

## 8. Configuration and Result Dataclasses

As a project grows, passing many unrelated arguments between functions becomes difficult to understand and easy to misuse. Python dataclasses provide named, structured containers for related information.

A configuration dataclass can hold inputs such as battery capacity, SOC bounds, efficiencies, power limits, timestep duration, initial SOC, and strategy settings. This provides one explicit description of a scenario and makes it easier to validate assumptions before a simulation starts.

A result dataclass can return the timeseries output, summary metrics, solver status, and relevant metadata together. This is clearer than returning a long positional tuple whose meaning depends on order.

Dataclasses improve engineering work by supporting:

- readable type-annotated interfaces;
- centralized validation;
- consistent scenario construction;
- easier serialization and experiment tracking;
- fewer hidden global values;
- safer refactoring.

The deeper concept is separation of concerns. Configuration describes what experiment to run. Dispatch code determines actions. The physical model enforces battery behavior. Metrics interpret results. Plots communicate them. Keeping these responsibilities separate makes the project easier to test and extend.

---

## 9. Reusable Experiment Data and Parameter Sweeps

A useful experiment must be repeatable. Reusable experiment data means that all strategies are evaluated on the same validated load, PV, price, and carbon signals, with the same units and boundary assumptions. This isolates the effect of the strategy from changes in the inputs.

A parameter sweep runs the same experiment repeatedly while changing one or more configuration values. Examples include varying battery capacity, power rating, efficiency, initial SOC, price threshold, carbon threshold, or degradation penalty.

The sweep workflow is:

1. define a baseline configuration;
2. generate controlled parameter combinations;
3. run the same simulation or optimization for each combination;
4. store parameters and metrics in tidy tabular form;
5. compare trends rather than isolated outcomes.

This is more informative than choosing one “reasonable” battery size and treating its result as universal. A sweep reveals nonlinear behavior, saturation, and tradeoffs. For example, increasing capacity may initially reduce cost sharply, then provide diminishing benefit when charge/discharge power or the available price spread becomes the limiting factor.

Reproducibility requires keeping everything except the intended parameter change constant. Otherwise, the result is not a sensitivity study; it is a comparison of different experiments.

---

## 10. Daily Analytics and Normalized KPIs

Raw quarter-hour output is necessary for diagnosis, but it is too detailed for comparing many scenarios. Daily analytics aggregate the chronological results into interpretable measures such as:

- grid import and export energy;
- PV generation, PV used on site, and PV curtailed;
- battery charge/discharge throughput;
- minimum, maximum, initial, and final SOC;
- electricity cost;
- grid-related emissions;
- peak grid demand;
- equivalent full cycles.

Aggregation must respect physical meaning. Power values are not simply summed to obtain energy; they are multiplied by interval duration first. Peaks use a maximum rather than a sum. State variables such as SOC may need starting, ending, minimum, and maximum values rather than an average alone.

Normalized key performance indicators (KPIs) allow comparisons across systems or days of different size. Examples include:

- cost per kWh of load served;
- emissions per kWh of load served;
- peak demand reduction as a percentage of the baseline peak;
- PV self-consumption as a fraction of PV generation;
- grid-energy reduction as a fraction of baseline grid import;
- savings or emissions reduction per unit of battery capacity;
- benefit per equivalent full cycle.

Every normalized KPI needs a clear denominator. “Carbon reduction percentage” is ambiguous unless it states the baseline and whether exported energy receives a carbon credit. A good metric definition includes a formula, units, sign convention, and treatment of edge cases such as a zero denominator.

---

## 11. Sensitivity Analysis: Testing Whether Conclusions Are Robust

Sensitivity analysis asks how much the result changes when an assumption changes. It is related to a parameter sweep but focuses on the reliability of conclusions rather than only exploring designs.

Possible sensitivities include battery efficiency, usable capacity, power rating, initial or terminal SOC, cycling cost, price forecast, carbon intensity, and control thresholds. If a small change in one assumption reverses the preferred strategy, the original recommendation is fragile and should be presented with caution.

A disciplined sensitivity analysis varies defined inputs, records identical metrics, and compares each case with a named baseline. It can reveal:

- parameters that have little influence;
- thresholds after which benefits saturate;
- tradeoffs between cost and emissions;
- assumptions responsible for most uncertainty;
- whether a controller is robust enough for practical use.

Sensitivity analysis prevents false precision. An optimization result may be numerically exact for its input data while the real engineering conclusion remains uncertain because future prices, carbon intensity, and battery characteristics are not known exactly.

---

## 12. Code Cleanup: From a Working Script to an Engineering Tool

Code cleanup is not cosmetic. It reduces the chance that a correct idea will be applied incorrectly later.

The Week 1 cleanup work emphasized small functions with clear responsibilities, descriptive names, documented units, explicit inputs and outputs, removal of duplicated logic, and separation between modeling, strategies, metrics, data preparation, and presentation.

A reusable structure makes it possible for rule-based and optimized strategies to share the same battery assumptions and metric calculations. Without this structure, two strategies may appear to be compared fairly while actually using different efficiency treatment, initial SOC, or cost formulas.

Good cleanup also preserves traceability. A result should be connectable to its configuration, input data, strategy, and metric definitions. This becomes especially important during parameter sweeps, where dozens of runs must be interpreted without manual reconstruction.

---

## 13. Pytest Testing: Encoding Model Invariants

Tests convert engineering expectations into repeatable checks. Pytest can confirm both ordinary examples and boundary conditions.

Useful battery tests include:

- charging increases stored energy by the expected efficiency-adjusted amount;
- discharging decreases stored energy correctly;
- SOC never exceeds its upper or lower bound;
- requested power is clipped to the battery rating;
- an empty battery cannot discharge;
- a full battery cannot charge;
- invalid configurations are rejected;
- power balance closes within numerical tolerance.

Dispatch tests can use small deterministic datasets where the expected action is obvious. Optimization tests should verify feasibility, status, constraint satisfaction, and expected qualitative behavior rather than relying only on an exact floating-point schedule. Solver outputs often require tolerance-based comparisons.

Parameterized tests apply the same invariant to multiple inputs, making boundary coverage concise. Regression tests preserve behavior after cleanup: if refactoring changes a trusted result unexpectedly, the test reveals it.

The broader lesson is that tests should focus on invariants—the statements that must remain true regardless of strategy. Conservation of energy, valid SOC, consistent units, and reproducible metrics are stronger guarantees than simply confirming that a function runs.

---

## 14. How the Week 1 Pieces Fit Together

The completed workflow can be understood as a chain:

1. **Data** supplies synchronized load, PV, price, and carbon signals.
2. **Configuration** records battery parameters and experiment assumptions.
3. **Battery equations** define feasible physical behavior.
4. **A dispatch rule or CVXPY model** chooses battery actions.
5. **The simulator** propagates SOC and grid power through time.
6. **Result structures** preserve the detailed trajectory and run metadata.
7. **Analytics and KPIs** translate trajectories into engineering outcomes.
8. **Sweeps and sensitivity analysis** test how outcomes change.
9. **Pytest** checks that physical and software invariants continue to hold.

The strongest Week 1 insight is that trustworthy optimization requires trustworthy foundations. A sophisticated solver cannot correct a bad timestamp join, an inconsistent sign convention, a missing efficiency term, or an unfair terminal SOC assumption.

---

## 15. Morning Review Checklist

Before moving into Week 2, you should be able to explain these ideas without looking at code:

- Why battery energy uses kWh while charge/discharge limits use kW.
- Why a 15-minute timestep multiplies power by 0.25 hours.
- Where charging and discharging efficiency enter the SOC equation.
- How the load, PV, battery, and grid terms satisfy power balance.
- Why timestamps and timezones affect physical and economic results.
- How rule-based dispatch differs from horizon-wide optimization.
- Why cost minimization and emissions minimization can disagree.
- Why initial and terminal SOC matter for fair comparisons.
- What EFC measures and what it leaves out.
- Why real API data needs validation, unit conversion, and reproducible snapshots.
- How dataclasses and separated modules make experiments safer to reuse.
- Why normalized KPIs require explicit denominators and baselines.
- How parameter sweeps and sensitivity analysis support different questions.
- Which physical invariants belong in automated tests.

---

## Optional Future Improvements — Not Required Week 1 Concepts

The following ideas are useful next steps, but they are not prerequisites for considering the completed Week 1 material learned:

- include demand charges, export tariffs, and explicit inverter or interconnection limits;
- prevent or discourage simultaneous charging and discharging with stronger formulations;
- use rolling-horizon or model-predictive control with updated forecasts;
- model forecast error and uncertainty through robust or stochastic optimization;
- replace simple EFC penalties with chemistry- and temperature-aware aging models;
- distinguish marginal from average carbon intensity according to the decision question;
- add persistent storage, command-line scenario execution, and richer reporting;
- validate the optimized power schedule in OpenDSS for voltage, current, and network constraints;
- explore multi-objective optimization and cost–emissions Pareto frontiers.

These improvements should be prioritized only after they support a required later-week objective or a clearly defined project need.

---

## Closing Summary

Week 1 established an end-to-end microgrid analysis foundation. You learned to represent battery physics, organize interval data, implement interpretable control rules, formulate cost and carbon optimization problems, quantify cycling, maintain continuity over multiple days, integrate real grid signals, structure reusable experiments, compare scenarios with meaningful KPIs, test sensitivity, clean the codebase, and protect model invariants with automated tests.

The result is more than a battery scheduling script. It is the beginning of a reproducible engineering system in which assumptions are explicit, alternatives can be compared fairly, and results can be checked against both physical laws and software tests.
