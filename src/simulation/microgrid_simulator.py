"""Provide user-facing microgrid simulation functions."""

import pandas as pd

from ..dispatch.battery import calculate_grid_power
from ..opendss.opendss_analysis import (
    replay_dispatch_timeseries,
)
from ..opendss.qsts_simulation import (
    replay_required_dispatch_scenarios,
)
from .input_validation import (
    validate_dispatch_scenarios,
    validate_snapshot_inputs,
)
from .model_specifications import (
    MicrogridSpecification,
)


def simulate_microgrid_snapshot(
    specification: MicrogridSpecification,
    *,
    timestamp: str | pd.Timestamp,
    pv_output_kw: float,
    battery_charge_kw: float = 0.0,
    battery_discharge_kw: float = 0.0,
) -> pd.DataFrame:
    """Simulate one user-defined microgrid operating point."""

    validate_snapshot_inputs(
        specification,
        pv_output_kw=pv_output_kw,
        battery_charge_kw=battery_charge_kw,
        battery_discharge_kw=battery_discharge_kw,
    )

    battery_net_injection_kw = (
        battery_discharge_kw
        - battery_charge_kw
    )

    grid_net_import_kw = calculate_grid_power(
        load_kw=specification.load_kw,
        pv_kw=pv_output_kw,
        charge_kw=battery_charge_kw,
        discharge_kw=battery_discharge_kw,
    )

    dispatch_data = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp(timestamp),
                "load_kw": specification.load_kw,
                "pv_kw": pv_output_kw,
                "battery_net_injection_kw": (
                    battery_net_injection_kw
                ),
                "grid_net_import_kw": grid_net_import_kw,
                "battery_soc_kWh": (
                    specification.battery.energy_kWh
                ),
            }
        ]
    )

    return replay_dispatch_timeseries(
        dispatch_data,
        battery=specification.battery,
        pv_capacity_kw=specification.pv_capacity_kw,
    )


def simulate_microgrid_scenarios(
    specification: MicrogridSpecification,
    dispatch_scenarios: dict[str, pd.DataFrame],
    *,
    timestep_minutes: int = 15,
) -> dict[str, pd.DataFrame]:
    """Replay multiple dispatch scenarios using one microgrid design."""

    validate_dispatch_scenarios(
        specification,
        dispatch_scenarios,
        timestep_minutes=timestep_minutes,
    )

    return replay_required_dispatch_scenarios(
        dispatch_scenarios,
        battery=specification.battery,
        pv_capacity_kw=specification.pv_capacity_kw,
    )
