"""Surplus-PV allocation and the interval power balance.

**Accounting convention: PV-first.**

Within each interval, available PV is allocated in this fixed priority order:

1. **Native load** -- PV displaces grid import first, because that is the
   highest-value use under any tariff with a positive import price.
2. **Battery charging** -- surplus beyond native load charges the battery, up
   to the battery's accepted charge power.
3. **Flexible load** -- if enabled, absorbs what remains.
4. **Grid export** -- if enabled, up to the export limit.
5. **Curtailment** -- whatever is still left is not produced.

This ordering is an *accounting* convention, not a claim about electrons. Real
power flow is determined by the network; the convention decides how a kWh is
labelled for reporting "self-consumed PV" and "battery charging attributed to
surplus PV". It matters because battery charge can come from PV or from the
grid, and the split is otherwise ambiguous.

Under PV-first, battery charging is attributed to PV only up to the PV
remaining after native load; any charging beyond that is grid-charged.

The interval identity that must always hold:

    pv_available
      = pv_serving_native_load
      + pv_charging_battery
      + flexible_load_supplied
      + grid_export
      + pv_curtailed
      + losses

and the bus balance:

    grid_import + pv_output + battery_discharge
      = native_load + flexible_load + battery_charge + grid_export
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..timeseries.schema import POWER_TOLERANCE_KW
from .configuration import SurplusConfiguration


class PowerBalanceError(ValueError):
    """An interval violates the power balance or a capability limit."""


@dataclass
class AllocationResult:
    """Per-interval surplus allocation, all columns in kW."""

    data: pd.DataFrame

    @property
    def frame(self) -> pd.DataFrame:
        return self.data


def allocate_surplus(
    timestamps: pd.Series | pd.DatetimeIndex,
    native_load_kw: np.ndarray,
    pv_available_kw: np.ndarray,
    surplus_configuration: SurplusConfiguration,
    *,
    battery_charge_kw: np.ndarray | None = None,
    battery_discharge_kw: np.ndarray | None = None,
) -> pd.DataFrame:
    """Allocate available PV across loads, battery, export and curtailment.

    ``battery_charge_kw`` and ``battery_discharge_kw`` are taken as already
    decided by the optimizer (or zero for a no-battery run). This function
    does not choose battery operation; it attributes energy and enforces the
    balance.
    """

    native_load = np.asarray(native_load_kw, dtype=float)
    pv_available = np.asarray(pv_available_kw, dtype=float)
    interval_count = len(native_load)

    if len(pv_available) != interval_count:
        raise PowerBalanceError(
            f"Native load has {interval_count} intervals but available PV has "
            f"{len(pv_available)}."
        )

    charge = _as_array(battery_charge_kw, interval_count, "battery charge")
    discharge = _as_array(
        battery_discharge_kw,
        interval_count,
        "battery discharge",
    )

    export_limit = surplus_configuration.grid_export.limit_for_intervals(
        interval_count
    )
    flexible_capacity = (
        surplus_configuration.flexible_load.availability_for_intervals(
            interval_count
        )
    )

    # 1. PV serves native load first.
    pv_to_native_load = np.minimum(pv_available, native_load)
    pv_remaining = pv_available - pv_to_native_load

    # 2. Surplus PV charges the battery, up to whatever charge the optimizer
    #    scheduled. Charging beyond available surplus is grid-charged.
    pv_to_battery = np.minimum(pv_remaining, charge)
    pv_remaining = pv_remaining - pv_to_battery
    grid_to_battery = charge - pv_to_battery

    # 3. Flexible load absorbs what it can.
    flexible_load = np.minimum(pv_remaining, flexible_capacity)
    pv_remaining = pv_remaining - flexible_load

    # 4. Export takes what the limit allows.
    grid_export = np.minimum(pv_remaining, export_limit)
    grid_export = np.where(np.isfinite(grid_export), grid_export, pv_remaining)
    pv_remaining = pv_remaining - grid_export

    # 5. Curtailment absorbs the rest. Always feasible.
    pv_curtailed = pv_remaining

    pv_output = pv_available - pv_curtailed

    # Residual native load and grid-charging are met by import.
    unmet_native_load = native_load - pv_to_native_load
    grid_import = np.maximum(
        unmet_native_load + grid_to_battery - discharge,
        0.0,
    )

    # Battery discharge beyond on-site need would have to go somewhere; with
    # export disabled that is infeasible, so surplus discharge is clipped into
    # the export channel where allowed.
    excess_discharge = np.maximum(
        discharge - (unmet_native_load + grid_to_battery),
        0.0,
    )

    remaining_export_headroom = np.where(
        np.isfinite(export_limit),
        np.maximum(export_limit - grid_export, 0.0),
        np.inf,
    )

    discharge_exported = np.minimum(
        excess_discharge,
        remaining_export_headroom,
    )
    discharge_exported = np.where(
        np.isfinite(discharge_exported),
        discharge_exported,
        excess_discharge,
    )

    grid_export = grid_export + discharge_exported

    total_load = native_load + flexible_load

    frame = pd.DataFrame(
        {
            "timestamp": pd.DatetimeIndex(timestamps),
            "native_load_kw": native_load,
            "flexible_load_kw": flexible_load,
            "total_load_kw": total_load,
            "pv_available_kw": pv_available,
            "pv_output_kw": pv_output,
            "pv_curtailed_kw": pv_curtailed,
            "pv_serving_native_load_kw": pv_to_native_load,
            "pv_charging_battery_kw": pv_to_battery,
            "grid_charging_battery_kw": grid_to_battery,
            "battery_charge_kw": charge,
            "battery_discharge_kw": discharge,
            "battery_net_injection_kw": discharge - charge,
            "grid_import_kw": grid_import,
            "grid_export_kw": grid_export,
            "grid_net_import_kw": grid_import - grid_export,
        }
    )

    return frame


def validate_power_balance(
    data: pd.DataFrame,
    *,
    tolerance_kw: float = 1e-6,
    losses_kw: np.ndarray | None = None,
) -> None:
    """Assert the PV identity and the bus balance hold in every interval."""

    losses = (
        np.zeros(len(data))
        if losses_kw is None
        else np.asarray(losses_kw, dtype=float)
    )

    pv_identity = (
        data["pv_serving_native_load_kw"]
        + data["pv_charging_battery_kw"]
        + data["flexible_load_kw"]
        + data["grid_export_kw"]
        + data["pv_curtailed_kw"]
        + losses
    )

    # Export may also be supplied by battery discharge, so the PV identity is
    # checked against PV output rather than against export alone.
    pv_allocated = (
        data["pv_serving_native_load_kw"]
        + data["pv_charging_battery_kw"]
        + data["pv_curtailed_kw"]
    )

    pv_residual = np.abs(
        data["pv_available_kw"].to_numpy(dtype=float)
        - pv_allocated.to_numpy(dtype=float)
        - data["flexible_load_kw"].to_numpy(dtype=float)
        - _pv_share_of_export(data)
    )

    if (pv_residual > tolerance_kw).any():
        position = int(np.argmax(pv_residual))
        raise PowerBalanceError(
            f"PV allocation does not balance at "
            f"{data['timestamp'].iloc[position]}: residual "
            f"{pv_residual[position]:.9f} kW exceeds {tolerance_kw} kW."
        )

    bus_supply = (
        data["grid_import_kw"]
        + data["pv_output_kw"]
        + data["battery_discharge_kw"]
    )

    bus_demand = (
        data["native_load_kw"]
        + data["flexible_load_kw"]
        + data["battery_charge_kw"]
        + data["grid_export_kw"]
    )

    bus_residual = np.abs(
        bus_supply.to_numpy(dtype=float)
        - bus_demand.to_numpy(dtype=float)
        - losses
    )

    if (bus_residual > tolerance_kw).any():
        position = int(np.argmax(bus_residual))
        raise PowerBalanceError(
            f"Bus power balance fails at "
            f"{data['timestamp'].iloc[position]}: supply "
            f"{bus_supply.iloc[position]:.6f} kW, demand "
            f"{bus_demand.iloc[position]:.6f} kW, residual "
            f"{bus_residual[position]:.9f} kW."
        )


def _pv_share_of_export(data: pd.DataFrame) -> np.ndarray:
    """Export attributable to PV under the PV-first convention."""

    return np.minimum(
        data["grid_export_kw"].to_numpy(dtype=float),
        np.maximum(
            data["pv_output_kw"].to_numpy(dtype=float)
            - data["pv_serving_native_load_kw"].to_numpy(dtype=float)
            - data["pv_charging_battery_kw"].to_numpy(dtype=float)
            - data["flexible_load_kw"].to_numpy(dtype=float),
            0.0,
        ),
    )


def validate_no_simultaneity(
    data: pd.DataFrame,
    *,
    tolerance_kw: float = POWER_TOLERANCE_KW,
) -> None:
    """Reject materially simultaneous import/export or charge/discharge.

    A convex formulation with positive import prices and nonnegative export
    compensation makes simultaneity economically dominated, so no
    mixed-integer solver is needed. This validates the resulting schedule
    rather than constraining it with binaries.
    """

    for first, second, label in (
        ("grid_import_kw", "grid_export_kw", "grid import and export"),
        (
            "battery_charge_kw",
            "battery_discharge_kw",
            "battery charge and discharge",
        ),
    ):
        if first not in data.columns or second not in data.columns:
            continue

        overlap = np.minimum(
            data[first].to_numpy(dtype=float),
            data[second].to_numpy(dtype=float),
        )

        if (overlap > tolerance_kw).any():
            position = int(np.argmax(overlap))
            raise PowerBalanceError(
                f"Materially simultaneous {label} at "
                f"{data['timestamp'].iloc[position]}: {overlap[position]:.6f} "
                f"kW overlap exceeds the {tolerance_kw} kW tolerance."
            )


def _as_array(values, interval_count: int, label: str) -> np.ndarray:
    if values is None:
        return np.zeros(interval_count)

    array = np.asarray(values, dtype=float)

    if len(array) != interval_count:
        raise PowerBalanceError(
            f"{label} has {len(array)} intervals but the horizon has "
            f"{interval_count}."
        )

    if (array < -POWER_TOLERANCE_KW).any():
        raise PowerBalanceError(f"{label} must be nonnegative.")

    if not np.isfinite(array).all():
        raise PowerBalanceError(f"{label} contains non-finite values.")

    return np.maximum(array, 0.0)
