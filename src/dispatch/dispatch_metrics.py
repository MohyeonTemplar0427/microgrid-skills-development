"""Calculate dispatch and battery-performance metrics."""

import pandas as pd


def calculate_dispatch_metrics(
    data: pd.DataFrame,
    timestep_hours: float = 0.25,
) -> dict[str, float]:
    """Calculate energy, cost, and emissions over any horizon."""

    grid_import_energy_kWh = (
        data["grid_import_kw"]
        * timestep_hours
    )

    total_grid_import_kWh = (
        grid_import_energy_kWh.sum()
    )

    total_cost = (
        grid_import_energy_kWh
        * data["price_per_kWh"]
    ).sum()

    total_emissions_kgCO2 = (
        grid_import_energy_kWh
        * data["gCO2/kWh"]
    ).sum() / 1000

    return {
        "grid_import_kWh": float(
            total_grid_import_kWh
        ),
        "cost": float(total_cost),
        "emissions_kgCO2": float(
            total_emissions_kgCO2
        ),
    }


def calculate_battery_usage_metrics(
    data: pd.DataFrame,
    battery_parameters: dict[str, float],
    timestep_hours: float = 0.25,
) -> dict[str, float]:
    """Calculate battery usage over any time horizon."""

    total_charge_kWh = (
        data["battery_charge_kw"]
        * timestep_hours
    ).sum()

    total_discharge_kWh = (
        data["battery_discharge_kw"]
        * timestep_hours
    ).sum()

    total_throughput_kWh = (
        total_charge_kWh
        + total_discharge_kWh
    )

    usable_capacity_kWh = (
        battery_parameters["max_soc_kWh"]
        - battery_parameters["min_soc_kWh"]
    )

    equivalent_full_cycles = (
        total_throughput_kWh
        / (2 * usable_capacity_kWh)
    )

    return {
        "charge_kWh": float(total_charge_kWh),
        "discharge_kWh": float(
            total_discharge_kWh
        ),
        "throughput_kWh": float(
            total_throughput_kWh
        ),
        "equivalent_full_cycles": float(
            equivalent_full_cycles
        ),
    }
