"""Provide an interactive console for microgrid simulations."""

from math import isfinite

import pandas as pd

from ..dispatch.battery import Battery
from .microgrid_simulator import (
    simulate_microgrid_snapshot,
)
from .model_specifications import (
    MicrogridSpecification,
)


def _prompt_float(
    prompt: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Request a finite floating-point value from the user."""

    while True:
        raw_value = input(prompt).strip()

        try:
            value = float(raw_value)
        except ValueError:
            print("Enter a valid number.")
            continue

        if not isfinite(value):
            print("Enter a finite number.")
            continue

        if minimum is not None and value < minimum:
            print(
                f"Enter a value greater than or equal to {minimum}."
            )
            continue

        if maximum is not None and value > maximum:
            print(
                f"Enter a value less than or equal to {maximum}."
            )
            continue

        return value


def prompt_microgrid_specification() -> MicrogridSpecification:
    """Collect physical microgrid parameters from the user."""

    print("\n=== Microgrid Specification ===")

    battery_capacity_kWh = _prompt_float(
        "Battery capacity (kWh): ",
        minimum=0.01,
    )

    minimum_energy_kWh = battery_capacity_kWh * 0.2

    maximum_energy_kWh = battery_capacity_kWh * 0.8

    battery_energy_kWh = _prompt_float(
        "Initial battery energy (kWh): ",
        minimum=minimum_energy_kWh,
        maximum=maximum_energy_kWh,
    )

    max_charge_kw = _prompt_float(
        "Maximum battery charging power (kW): ",
        minimum=0.01,
    )

    max_discharge_kw = _prompt_float(
        "Maximum battery discharging power (kW): ",
        minimum=0.01,
    )

    pv_capacity_kw = _prompt_float(
        "PV capacity (kW): ",
        minimum=0.01,
    )

    load_kw = _prompt_float(
        "Load power (kW): ",
        minimum=0.0,
    )

    battery = Battery(
        capacity_kWh=battery_capacity_kWh,
        energy_kWh=battery_energy_kWh,
        max_charge_kw=max_charge_kw,
        max_discharge_kw=max_discharge_kw,
    )

    return MicrogridSpecification(
        battery=battery,
        pv_capacity_kw=pv_capacity_kw,
        load_kw=load_kw,
    )


def run_console_snapshot() -> pd.DataFrame:
    """Collect inputs, run one snapshot, and display key results."""

    specification = (
        prompt_microgrid_specification()
    )

    print("\n=== Operating Point ===")

    pv_output_kw = _prompt_float(
        "Current PV output (kW): ",
        minimum=0.0,
        maximum=specification.pv_capacity_kw,
    )

    battery_net_injection_kw = _prompt_float(
        "Battery power, positive discharge and negative charge (kW): ",
        minimum=-specification.battery.max_charge_kw,
        maximum=specification.battery.max_discharge_kw,
    )

    battery_charge_kw = max(
        -battery_net_injection_kw,
        0.0,
    )
    battery_discharge_kw = max(
        battery_net_injection_kw,
        0.0,
    )

    results = simulate_microgrid_snapshot(
        specification,
        timestamp=pd.Timestamp.now(),
        pv_output_kw=pv_output_kw,
        battery_charge_kw=battery_charge_kw,
        battery_discharge_kw=battery_discharge_kw,
    )

    result = results.iloc[0]

    print("\n=== Simulation Results ===")
    print(f"Converged: {bool(result['converged'])}")
    print(
        "Scheduled grid import: "
        f"{result['scheduled_grid_import_kw']:.4f} kW"
    )
    print(
        "OpenDSS PCC grid import: "
        f"{result['pcc_grid_net_import_kw']:.4f} kW"
    )
    print(
        "Minimum voltage: "
        f"{result['minimum_voltage_pu']:.4f} pu"
    )
    print(
        "Maximum line loading: "
        f"{result['line_loading_percent']:.4f}%"
    )
    print(
        "Transformer loading: "
        f"{result['transformer_loading_percent']:.4f}%"
    )
    print(
        f"Feasible: {bool(result['feasible'])}"
    )

    return results


def main() -> None:
    """Run the interactive microgrid snapshot interface."""

    run_console_snapshot()


if __name__ == "__main__":
    main()
