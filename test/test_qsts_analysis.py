"""Tests for QSTS analysis utilities."""

import pandas as pd
import pytest

from src.qsts_analysis import(
    create_no_battery_replay_schedule,
    create_qsts_scenario_comparison
)

def test_create_no_battery_replay_schedule():
    dispatch_data = pd.DataFrame(
        {
            "load_kw": [10.0, 5.0],
            "pv_kw": [2.0, 8.0],
            "battery_charge_kw": [0.0, 2.0],
            "battery_discharge_kw": [3.0, 0.0],
            "battery_net_injection_kw": [3.0, -2.0],
            "grid_import_kw": [5.0, 0.0],
            "grid_export_kw": [0.0, 1.0],
            "grid_net_import_kw": [5.0, -1.0],
        }
    )

    result = create_no_battery_replay_schedule(
        dispatch_data
    )

    assert result["battery_charge_kw"].tolist() == [
        0.0,
        0.0,
    ]

    assert result["battery_discharge_kw"].tolist() == [
        0.0,
        0.0,
    ]

    assert result["battery_net_injection_kw"].tolist() == [
        0.0,
        0.0,
    ]

    assert result["grid_net_import_kw"].tolist() == (
        pytest.approx([8.0, -3.0])
    )

    assert result["grid_import_kw"].tolist() == (
        pytest.approx([8.0, 0.0])
    )

    assert result["grid_export_kw"].tolist() == (
        pytest.approx([0.0, 3.0])
    )

def test_create_qsts_scenario_comparison():
    optimized_results = pd.DataFrame(
        {
            "converged": [True, True],
            "minimum_voltage_pu": [0.99, 0.98],
            "maximum_voltage_pu": [1.01, 1.02],
            "maximum_current_a": [20.0, 30.0],
            "scheduled_grid_import_kw": [10.0, -2.0],
            "feeder_real_loss_kw": [1.0, 3.0],
            "feasible": [True, True],
            "voltage_violation": [False, False],
            "line_overload": [False, False],
            "transformer_overload": [False, False],
            "reverse_power_flow": [False, True],
            "line_loading_percent": [20.0, 30.0],
            "transformer_loading_percent": [40.0, 50.0],
            "transformer_real_loss_kw": [0.2, 0.4],
            "pcc_grid_import_kw": [10.0, 0.0],
            "pcc_grid_export_kw": [0.0, 2.0],
        }
    )

    no_battery_results = pd.DataFrame(
        {
            "converged": [True, False],
            "minimum_voltage_pu": [0.97, 0.96],
            "maximum_voltage_pu": [1.00, 1.01],
            "maximum_current_a": [25.0, 35.0],
            "scheduled_grid_import_kw": [12.0, -4.0],
            "feeder_real_loss_kw": [2.0, 4.0],
            "feasible": [True, False],
            "voltage_violation": [False, True],
            "line_overload": [False, False],
            "transformer_overload": [False, False],
            "reverse_power_flow": [False, True],
            "line_loading_percent": [25.0, 35.0],
            "transformer_loading_percent": [45.0, 55.0],
            "transformer_real_loss_kw": [0.3, 0.5],
            "pcc_grid_import_kw": [12.0, 0.0],
            "pcc_grid_export_kw": [0.0, 4.0],
        }
    )

    comparison = (
        create_qsts_scenario_comparison(
            {
                "optimized": optimized_results,
                "no_battery": no_battery_results,
            },
            timestep_hours=0.25,
        )
        .set_index("scenario")
    )

    assert comparison.loc[
        "optimized",
        "interval_count",
    ] == 2

    assert comparison.loc[
        "optimized",
        "converged_intervals",
    ] == 2

    assert comparison.loc[
        "no_battery",
        "converged_intervals",
    ] == 1

    assert comparison.loc[
        "optimized",
        "minimum_voltage_pu",
    ] == pytest.approx(0.98)

    assert comparison.loc[
        "optimized",
        "maximum_current_a",
    ] == pytest.approx(30.0)

    assert comparison.loc[
        "optimized",
        "peak_grid_import_kw",
    ] == pytest.approx(10.0)

    assert comparison.loc[
        "optimized",
        "minimum_grid_power_kw",
    ] == pytest.approx(-2.0)

    assert comparison.loc[
        "optimized",
        "feeder_loss_energy_kWh",
    ] == pytest.approx(1.0)

    assert comparison.loc[
        "no_battery",
        "feeder_loss_energy_kWh",
    ] == pytest.approx(1.5)

    assert comparison.loc[
        "optimized",
        "feasible_intervals",
    ] == 2

    assert comparison.loc[
        "no_battery",
        "feasible_intervals",
    ] == 1

    assert comparison.loc[
        "no_battery",
        "voltage_violation_intervals",
    ] == 1

    assert comparison.loc[
        "optimized",
        "reverse_power_flow_intervals",
    ] == 1
    assert comparison.loc[
        "optimized",
        "maximum_line_loading_percent",
    ] == pytest.approx(30.0)

    assert comparison.loc[
        "optimized",
        "maximum_transformer_loading_percent",
    ] == pytest.approx(50.0)

    assert comparison.loc[
        "optimized",
        "grid_import_energy_kWh",
    ] == pytest.approx(2.5)

    assert comparison.loc[
        "optimized",
        "grid_export_energy_kWh",
    ] == pytest.approx(0.5)

    assert comparison.loc[
        "optimized",
        "transformer_loss_energy_kWh",
    ] == pytest.approx(0.15) 