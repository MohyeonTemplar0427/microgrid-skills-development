"""Provide user-facing microgrid simulation functions."""
#### Package Import #######################################################################
import pandas as pd

from ..dispatch.battery import calculate_grid_power
from ..opendss.opendss_analysis import(
    replay_dispatch_timeseries,
)
from ..opendss.qsts_simulation import(
    replay_required_dispatch_scenarios,
)
from.model_specifications import(
    MicrogridSpecification,
)

###############################################################################3

def simulate_microgrid_snapshot(
    specification: MicrogridSpecification,
    *,
    timestamp: str | pd.Timestamp,
    pv_output_kw: float,
    battery_charge_kw: float = 0.0,
    battery_discharge_kw: float = 0.0,
) -> pd.DataFrame:
    """Simulate one user-defined microgrid operating point."""

    if not isinstance(
        specification,
        MicrogridSpecification,
    ):
        raise TypeError(
            "specification must be a MicrogridSpecification object."
        )

    if not(
        0.0 <= pv_output_kw <= specification.pv_capacity_kw
    ):
        raise ValueError(
            "PV output not in accepatable range"
        )

    if battery_charge_kw < 0:
        raise ValueError(
            "Battery charging power must not be negative."
        )

    if battery_charge_kw > 0 and battery_discharge_kw > 0:
        raise ValueError(
            "The battery cannot charge and discharge simultaneously."
        )

    if battery_charge_kw > specification.battery.max_charge_kw:
        raise ValueError(
            "Battery charge power exceeds limit."
        )

    if battery_discharge_kw > specification.battery.max_discharge_kw:
        raise ValueError(
            "Battery discharging power exceeds limit."
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
                "battery_net_injection_kw": battery_net_injection_kw,
                "grid_net_import_kw": grid_net_import_kw,
                "battery_soc_kWh": specification.battery.energy_kWh,
            }
        ]
    )

    return replay_dispatch_timeseries(
        dispatch_data,
        battery=specification.battery,
        pv_capacity_kw=(
            specification.pv_capacity_kw
        ),
    )

def simulate_microgrid_scenarios(
    specification: MicrogridSpecification,
    dispatch_scenarios: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Replay multiple dispatch scenarios using one microgrid design."""

    if not isinstance(
        specification,
        MicrogridSpecification,
    ):
        raise TypeError(
            "Object not matched as MicrogridSpecification."
        )

    return replay_required_dispatch_scenarios(
        dispatch_scenarios,
        battery=specification.battery,
        pv_capacity_kw=specification.pv_capacity_kw,
    )

