# Prompt Writing Guide — Session_Week1

## Why this matters here specifically

This repo is a physical simulation, not a typical CRUD app. Sign errors, unit
mismatches, and boundary-condition mistakes (e.g. terminal SOC, timestep
conversion) can produce code that *runs* and even passes loose tests while
being physically wrong. A vague prompt tends to produce exactly that kind of
bug. Two things make prompt quality matter more on this project than usual:

1. **Conventions live in your head, not in the code.** Sign convention, units,
   timezone, and the 15-minute timestep all need to be restated in a prompt,
   or the AI will guess.
2. **This repo is worked on from more than one AI tool.** State can diverge
   between sessions. A prompt that assumes "the last thing we did" without
   checking `git status` / `git log` first risks conflicting with work done
   elsewhere.

## The template

For any nontrivial change, structure the prompt as:

```
GOAL: <one sentence, in engineering terms not code terms>
SCOPE: <which file(s)/function(s) — or "figure out where this belongs">
INVARIANTS TO PRESERVE: <sign convention / units / timestep / SOC bounds / whatever applies>
VERIFY FIRST: check git status and current test results before assuming prior state
DONE WHEN: <pytest passes / specific numeric check / new artifact matches expected shape>
```

You don't need all five lines for a one-line fix, but for anything touching
`src/battery.py`, `src/market_data_integration.py`, or the optimizer, the
middle three lines are what prevents silent physical bugs.

## Concrete before/after

**Vague (bad):**
> "Add a demand charge to the cost calculation"

**Specific (good):**
> "Add a monthly demand charge to the cost objective in
> `market_data_integration.py`. It should be `$/kW × max(grid_import_kw over
> the horizon)`, added once per scenario, not per-timestep. Keep the existing
> sign convention (`grid_net_import_kw = grid_import_kw − grid_export_kw`,
> positive = import). Add a test in `test/test_market_data_integration.py`
> that a lower peak-shaving battery reduces the demand charge term
> specifically, holding energy cost constant. Run `pytest -q` after."

The vague version is ambiguous about whether the charge is per-interval or
per-billing-period — the kind of ambiguity that produces a number off by
~96x (one 15-min interval vs. a full day) without anyone noticing until a
KPI looks wrong.

**Vague:**
> "Make the battery model more realistic"

**Specific:**
> "Extend `Battery` in `battery.py` to reject a charge/discharge request that
> would push SOC outside `[min_soc, max_soc]`, clipping to the feasible power
> rather than raising. Add boundary tests: full battery can't charge, empty
> battery can't discharge, requested power above rating gets clipped —
> matching the invariant list in `Week_1_Microgrid_Skills_Study_Guide.md`
> §13."

## Repo-specific checklist

State these explicitly in a prompt rather than assuming the AI infers them
correctly:

- **Units** — kW for power, kWh for energy/capacity; `$/MWh` needs
  conversion before multiplying by kWh.
- **Sign convention** — grid import positive, battery discharge positive to
  the feeder:
  - `grid_net_import_kw = grid_import_kw − grid_export_kw`
  - `battery_net_injection_kw = battery_discharge_kw − battery_charge_kw`
  (see `Week_2_Completion_Recap.md`).
- **Timestep** — 15 min = 0.25 h. Say so if the change involves any
  power→energy conversion.
- **Initial/terminal SOC** — state which convention (fixed / minimum / free)
  if the change touches the optimizer's boundary conditions; this silently
  changes comparability between scenarios.
- **Reproducibility** — don't let a prompt trigger a live API call inside a
  test; point to the cached/validated data-snapshot approach used in Week 2
  instead.
- **"Done when"** — name `pytest -q`, and if the change regenerates
  artifacts, name which file in `results/` should change and how to sanity
  check it (e.g. "the OpenDSS handoff should still be 192 continuous 15-min
  intervals").

## One habit for working across multiple AI tools

Open prompts that continue prior work with a verification step instead of an
assumption:

> "Before changing anything, run `git log --oneline -5` and `git status` and
> tell me what state we're actually in — I've been alternating between
> sessions/tools on this repo."

Cheap, and it prevents a prompt built on a stale mental model of what's
already implemented.
