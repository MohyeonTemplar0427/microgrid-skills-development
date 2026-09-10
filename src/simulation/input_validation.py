"""Validate user-provided microgrid simulation inputs."""

import pandas as pd

from .model_specifications import MicrogridSpecification


def _validate_specification(
    specification: MicrogridSpecification,
) -> None:
    """Ensure the simulation received a microgrid specification."""

    if not isinstance(
        specification,
        MicrogridSpecification,
    ):
        raise TypeError(
            "specification must be a MicrogridSpecification object."
        )


def validate_snapshot_inputs(
    specification: MicrogridSpecification,
    *,
    pv_output_kw: float,
    battery_charge_kw: float,
    battery_discharge_kw: float,
) -> None:
    """Validate one user-defined microgrid operating point."""

    _validate_specification(specification)

    if not (
        0.0
        <= pv_output_kw
        <= specification.pv_capacity_kw
    ):
        raise ValueError(
            "PV output must be between zero and the PV capacity."
        )

    if battery_charge_kw < 0:
        raise ValueError(
            "Battery charging power must not be negative."
        )

    if battery_discharge_kw < 0:
        raise ValueError(
            "Battery discharging power must not be negative."
        )

    if battery_charge_kw > 0 and battery_discharge_kw > 0:
        raise ValueError(
            "The battery cannot charge and discharge simultaneously."
        )

    if battery_charge_kw > specification.battery.max_charge_kw:
        raise ValueError(
            "Battery charge power exceeds limit."
        )

    if (
        battery_discharge_kw
        > specification.battery.max_discharge_kw
    ):
        raise ValueError(
            "Battery discharging power exceeds limit."
        )


def _validate_battery_dispatch_limits(
    specification: MicrogridSpecification,
    dispatch_data: pd.DataFrame,
) -> None:
    """Ensure every battery command respects its power ratings."""

    column_name = "battery_net_injection_kw"

    if column_name not in dispatch_data.columns:
        raise ValueError(
            f"Dispatch data is missing {column_name}."
        )

    battery_power_kw = dispatch_data[column_name]

    if (
        battery_power_kw
        > specification.battery.max_discharge_kw
    ).any():
        raise ValueError(
            "Battery dispatch exceeds the discharge-power limit."
        )

    if (
        battery_power_kw
        < -specification.battery.max_charge_kw
    ).any():
        raise ValueError(
            "Battery dispatch exceeds the charge-power limit."
        )


def _validate_battery_energy_limits(
    specification: MicrogridSpecification,
    dispatch_data: pd.DataFrame,
    *,
    tolerance_kWh: float = 1e-6,
) -> None:
    """Ensure every scheduled battery energy remains within SOC limits."""

    column_name = "battery_soc_kWh"

    if column_name not in dispatch_data.columns:
        raise ValueError(
            f"Dispatch data is missing {column_name}."
        )

    battery_energy_kWh = dispatch_data[column_name]

    minimum_energy_kWh = (
        specification.battery.minimum_energy_kWh
        - tolerance_kWh
    )
    maximum_energy_kWh = (
        specification.battery.maximum_energy_kWh
        + tolerance_kWh
    )

    if (
        battery_energy_kWh < minimum_energy_kWh
    ).any():
        raise ValueError(
            "Battery dispatch falls below the minimum SOC."
        )

    if (
        battery_energy_kWh > maximum_energy_kWh
    ).any():
        raise ValueError(
            "Battery dispatch exceeds the maximum SOC."
        )


def _validate_pv_dispatch_limits(
    specification: MicrogridSpecification,
    dispatch_data: pd.DataFrame,
) -> None:
    """Ensure every PV output remains within its physical rating."""

    column_name = "pv_kw"

    if column_name not in dispatch_data.columns:
        raise ValueError(
            f"Dispatch data is missing {column_name}."
        )

    pv_output_kw = dispatch_data[column_name]

    if (pv_output_kw < 0.0).any():
        raise ValueError(
            "PV output must not be negative."
        )

    if (
        pv_output_kw > specification.pv_capacity_kw
    ).any():
        raise ValueError(
            "PV output exceeds the configured PV capacity."
        )


def _validate_load_dispatch(
    dispatch_data: pd.DataFrame,
) -> None:
    """Ensure every scheduled load value is nonnegative."""

    column_name = "load_kw"

    if column_name not in dispatch_data.columns:
        raise ValueError(
            f"Dispatch data is missing {column_name}."
        )

    load_kw = dispatch_data[column_name]

    if (load_kw < 0.0).any():
        raise ValueError(
            "Load power must not be negative."
        )


def _validate_dispatch_power_balance(
    dispatch_data: pd.DataFrame,
    *,
    tolerance_kw: float = 1e-6,
) -> None:
    """Ensure scheduled grid power satisfies the power balance."""

    required_columns = {
        "load_kw",
        "pv_kw",
        "battery_net_injection_kw",
        "grid_net_import_kw",
    }

    missing_columns = (
        required_columns - set(dispatch_data.columns)
    )

    if missing_columns:
        raise ValueError(
            "Power-balance data is missing columns: "
            f"{sorted(missing_columns)}"
        )

    expected_grid_import_kw = (
        dispatch_data["load_kw"]
        - dispatch_data["pv_kw"]
        - dispatch_data["battery_net_injection_kw"]
    )

    balance_error_kw = (
        dispatch_data["grid_net_import_kw"]
        - expected_grid_import_kw
    ).abs()

    if (balance_error_kw > tolerance_kw).any():
        raise ValueError(
            "Dispatch schedule does not satisfy power balance."
        )


def _validate_dispatch_timestamps(
    dispatch_data: pd.DataFrame,
    *,
    timestep_minutes: int,
) -> None:
    """Ensure dispatch timestamps are valid, unique, and continuous."""

    if timestep_minutes <= 0:
        raise ValueError(
            "Timestep minutes must be positive."
        )

    column_name = "timestamp"

    if column_name not in dispatch_data.columns:
        raise ValueError(
            f"Dispatch data is missing {column_name}."
        )

    timestamps = pd.to_datetime(
        dispatch_data[column_name],
        errors="coerce",
    )

    if timestamps.isna().any():
        raise ValueError(
            "Dispatch data contains an invalid timestamp."
        )

    if not timestamps.is_unique:
        raise ValueError(
            "Dispatch data contains duplicate timestamps."
        )

    if not timestamps.is_monotonic_increasing:
        raise ValueError(
            "Dispatch timestamps must be in increasing order."
        )

    interval_differences = (
        timestamps.diff().dropna()
    )
    expected_interval = pd.Timedelta(
        minutes=timestep_minutes,
    )

    if not (
        interval_differences == expected_interval
    ).all():
        raise ValueError(
            "Dispatch timestamps are not continuous "
            f"{timestep_minutes}-minute intervals."
        )


def validate_dispatch_scenarios(
    specification: MicrogridSpecification,
    dispatch_scenarios: dict[str, pd.DataFrame],
    *,
    timestep_minutes: int,
) -> None:
    """Validate every scenario before starting OpenDSS replay."""

    _validate_specification(specification)

    for dispatch_data in dispatch_scenarios.values():
        _validate_dispatch_timestamps(
            dispatch_data,
            timestep_minutes=timestep_minutes,
        )
        _validate_battery_dispatch_limits(
            specification,
            dispatch_data,
        )
        _validate_battery_energy_limits(
            specification,
            dispatch_data,
        )
        _validate_pv_dispatch_limits(
            specification,
            dispatch_data,
        )
        _validate_load_dispatch(dispatch_data)
        _validate_dispatch_power_balance(dispatch_data)


__all__ = [
    "validate_dispatch_scenarios",
    "validate_snapshot_inputs",
]
