"""Tests for the user-facing microgrid simulator."""

import pandas as pd

from src.dispatch.battery import Battery
from src.simulation.microgrid_simulator import (
    simulate_microgrid_scenarios,
)
from src.simulation.model_specifications import (
    MicrogridSpecification,
)


def test_simulate_microgrid_scenarios_replays_selected_scenario():
    # Arrange
    battery = Battery(
        capacity_kWh=20.0,
        SOC_min=0.1,
        SOC_max=0.9,
        energy_kWh=10.0,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
    )

    specification = MicrogridSpecification(
        battery=battery,
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    dispatch_data = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp(
                    "2026-08-25 12:00:00"
                ),
                "load_kw": 25.0,
                "pv_kw": 10.0,
                "battery_net_injection_kw": 0.0,
                "grid_net_import_kw": 15.0,
                "battery_soc_kWh": 10.0,
            }
        ]
    )

    # Act
    results = simulate_microgrid_scenarios(
        specification,
        {
            "custom_scenario": dispatch_data,
        },
    )

    # Assert
    assert set(results) == {
        "custom_scenario",
    }

    scenario_result = results[
        "custom_scenario"
    ]

    assert len(scenario_result) == 1
    assert bool(
        scenario_result.loc[0, "converged"]
    )
    assert (
        scenario_result.loc[
            0,
            "scheduled_grid_import_kw",
        ]
        == 15.0
    )

