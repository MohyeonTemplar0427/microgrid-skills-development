"""The no-battery baseline.

A no-battery run represents the *absence* of storage. It needs no battery
parameters, and constructing a stand-in ``Battery`` to describe "no battery"
is a category error: ``Battery`` validates that capacity, power limits and
efficiencies are physically real, so a zero-capacity instance cannot be built
without weakening validation that genuine batteries depend on.

Everything here derives from the site's own load and PV. When ``no_battery``
is the only selected strategy, nothing in this module reads a user-entered
battery parameter, so those values cannot influence the result.
"""

import numpy as np
import pandas as pd

# Every quantity that describes battery operation, pinned to zero.
NO_BATTERY_DISPATCH_COLUMNS = (
    "battery_charge_kw",
    "battery_discharge_kw",
    "battery_net_injection_kw",
)

NO_BATTERY_USAGE_METRICS = {
    "charge_kWh": 0.0,
    "discharge_kWh": 0.0,
    "throughput_kWh": 0.0,
    "equivalent_full_cycles": 0.0,
}

REQUIRED_SIGNAL_COLUMNS = frozenset(
    {
        "timestamp",
        "load_kw",
        "pv_kw",
        "net_load_kw",
    }
)


class NoBatteryContractError(ValueError):
    pass


def create_no_battery_dispatch(
    signal_data: pd.DataFrame,
    *,
    zero_tolerance_kw: float = 1e-6,
) -> pd.DataFrame:
    """Build the no-battery dispatch schedule from load and PV alone.

    Requires no battery parameters. Grid import is unmet net load and grid
    export is surplus PV, split so neither is ever negative.
    """

    missing = REQUIRED_SIGNAL_COLUMNS - set(signal_data.columns)

    if missing:
        raise NoBatteryContractError(
            f"No-battery dispatch is missing required columns: "
            f"{sorted(missing)}"
        )

    if signal_data.empty:
        raise NoBatteryContractError(
            "No-battery dispatch data must not be empty."
        )

    dispatch = signal_data.copy()

    net_load = dispatch["net_load_kw"]

    dispatch["grid_import_kw"] = net_load.clip(lower=0.0)
    dispatch["grid_export_kw"] = (-net_load).clip(lower=0.0)

    for column in NO_BATTERY_DISPATCH_COLUMNS:
        dispatch[column] = 0.0

    dispatch["grid_net_import_kw"] = (
        dispatch["grid_import_kw"] - dispatch["grid_export_kw"]
    )

    validate_no_battery_dispatch(
        dispatch,
        zero_tolerance_kw=zero_tolerance_kw,
    )

    return dispatch


def validate_no_battery_dispatch(
    dispatch: pd.DataFrame,
    *,
    zero_tolerance_kw: float = 1e-6,
) -> None:
    """Assert that no battery operation appears anywhere in the schedule."""

    for column in NO_BATTERY_DISPATCH_COLUMNS:
        if column not in dispatch.columns:
            raise NoBatteryContractError(
                f"No-battery dispatch is missing {column}."
            )

        values = pd.to_numeric(dispatch[column], errors="coerce")

        if values.isna().any():
            raise NoBatteryContractError(
                f"No-battery dispatch column {column} contains nonnumeric "
                f"values."
            )

        largest = float(np.abs(values.to_numpy(dtype=float)).max())

        if largest > zero_tolerance_kw:
            raise NoBatteryContractError(
                f"No-battery dispatch has nonzero {column}: peak magnitude "
                f"{largest} kW exceeds the {zero_tolerance_kw} kW tolerance."
            )


def no_battery_usage_metrics() -> dict[str, float]:
    """Battery usage for a run with no battery: all zero.

    Deliberately not routed through ``calculate_battery_usage_metrics``,
    which computes equivalent full cycles as throughput divided by usable
    capacity. With no battery there is no usable capacity, and that division
    is undefined rather than zero.
    """

    return dict(NO_BATTERY_USAGE_METRICS)


def no_battery_cost_metrics(
    dispatch: pd.DataFrame,
    price_data: pd.DataFrame,
    carbon_data: pd.DataFrame,
    *,
    timestep_hours: float = 0.25,
) -> dict[str, float]:
    """Cost and emissions for the no-battery baseline.

    Degradation cost is structurally zero: there is no throughput to degrade
    anything, whatever degradation rate the user entered.
    """

    from ..signal_pipeline.timeseries_validation import (
        merge_complete_time_series,
    )

    grid = dispatch[["timestamp", "grid_import_kw"]].copy()

    with_price = merge_complete_time_series(
        grid,
        price_data[["timestamp", "price_per_kWh"]],
        right_name="Price",
    )

    with_carbon = merge_complete_time_series(
        grid,
        carbon_data[["timestamp", "gCO2/kWh"]],
        right_name="Carbon",
    )

    cost = float(
        (
            with_price["grid_import_kw"]
            * timestep_hours
            * with_price["price_per_kWh"]
        ).sum()
    )

    emissions_kgCO2 = float(
        (
            with_carbon["grid_import_kw"]
            * timestep_hours
            * with_carbon["gCO2/kWh"]
        ).sum()
        / 1000
    )

    usage = no_battery_usage_metrics()

    return {
        "cost": cost,
        "emissions_kgCO2": emissions_kgCO2,
        "battery_throughput_kWh": usage["throughput_kWh"],
        "equivalent_full_cycles": usage["equivalent_full_cycles"],
        "degradation_cost": 0.0,
        "total_operating_cost": cost,
    }


def battery_parameters_are_required(strategies) -> bool:
    """True when any selected strategy actually operates a battery.

    The frontend can call this to decide whether to collect battery inputs at
    all. When it returns False, battery fields can be skipped entirely rather
    than collected and ignored.
    """

    operating_strategies = set(strategies) - {"no_battery"}

    return bool(operating_strategies)
