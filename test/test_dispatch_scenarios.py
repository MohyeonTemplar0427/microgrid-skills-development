"""Tests for Week 4 dispatch-scenario construction."""

import pandas as pd
import pytest

from src.dispatch import single_day_analysis as sda
from src.dispatch.dispatch_scenarios import (
        SCENARIO_OUTPUT_FILENAMES,
    create_optimized_dispatch_scenarios,
    create_required_dispatch_scenarios,
    save_required_dispatch_scenarios,
)



def test_create_optimized_dispatch_scenarios():
    input_data = sda.create_sample_dataframe(
        date="2026-08-25"
    )

    original_columns = input_data.columns.tolist()

    scenarios = create_optimized_dispatch_scenarios(
        input_data,
        sda.battery_parameters,
        carbon_weight=0.20,
        degradation_cost_per_kWh=0.03,
    )

    assert set(scenarios) == {
        "rule_based",
        "cost_optimal",
        "carbon_optimal",
        "combined_optimal",
    }

    # Each optimizer must receive a copy rather than
    # modifying the shared input DataFrame.
    assert input_data.columns.tolist() == original_columns

    for schedule in scenarios.values():
        assert len(schedule) == 96

        assert (
            schedule["power_balance_error_kw"]
            .abs()
            .max()
            < 1e-6
        )

        assert {
            "battery_charge_kw",
            "battery_discharge_kw",
            "battery_soc_kWh",
            "grid_import_kw",
            "grid_export_kw",
        }.issubset(schedule.columns)


def test_create_required_dispatch_scenarios():
    input_data = sda.create_sample_dataframe(
        date="2026-08-25"
    )

    scenarios = create_required_dispatch_scenarios(
        input_data,
        sda.battery_parameters,
        carbon_weight=0.20,
        degradation_cost_per_kWh=0.03,
    )

    assert list(scenarios) == [
        "no_battery",
        "rule_based",
        "cost_optimal",
        "carbon_optimal",
        "combined_optimal",
    ]

    required_columns = {
        "timestamp",
        "load_kw",
        "pv_kw",
        "battery_charge_kw",
        "battery_discharge_kw",
        "battery_net_injection_kw",
        "grid_import_kw",
        "grid_export_kw",
        "grid_net_import_kw",
        "battery_soc_kWh",
    }

    for schedule in scenarios.values():
        assert len(schedule) == 96
        assert required_columns.issubset(
            schedule.columns
        )

    no_battery = scenarios["no_battery"]

    assert (
        no_battery["battery_net_injection_kw"]
        .abs()
        .max()
        == 0.0
    )

    assert (
        no_battery["battery_soc_kWh"]
        == sda.battery_parameters[
            "initial_soc_kWh"
        ]
    ).all()


def test_create_required_dispatch_scenarios_skips_unselected_optimizers(
    monkeypatch,
):
    input_data = sda.create_sample_dataframe(
        date="2026-08-25"
    )

    def unexpected_call(*args, **kwargs):
        pytest.fail("An unselected optimizer was called.")

    monkeypatch.setattr(sda, "run_rule_based_dispatch", unexpected_call)
    monkeypatch.setattr(sda, "run_cost_optimization", unexpected_call)
    monkeypatch.setattr(sda, "run_carbon_optimization", unexpected_call)
    monkeypatch.setattr(sda, "run_combined_optimization", unexpected_call)

    scenarios = create_required_dispatch_scenarios(
        input_data,
        sda.battery_parameters,
        carbon_weight=0.20,
        degradation_cost_per_kWh=0.03,
        scenario_names=("no_battery",),
    )

    assert tuple(scenarios) == ("no_battery",)
    assert scenarios["no_battery"][
        "battery_net_injection_kw"
    ].eq(0.0).all()


def test_save_required_dispatch_scenarios(
    tmp_path,
):
    scenarios = {}

    for scenario_name in (
        SCENARIO_OUTPUT_FILENAMES
    ):
        scenarios[scenario_name] = (
            pd.DataFrame(
                {
                    "scenario": [
                        scenario_name
                    ],
                    "value": [1.0],
                }
            )
        )

    saved_paths = (
        save_required_dispatch_scenarios(
            scenarios,
            tmp_path,
        )
    )

    assert set(saved_paths) == set(
        SCENARIO_OUTPUT_FILENAMES
    )

    for scenario_name, output_path in (
        saved_paths.items()
    ):
        assert output_path.exists()
        assert output_path.parent == tmp_path

        saved_data = pd.read_csv(
            output_path
        )

        assert saved_data[
            "scenario"
        ].tolist() == [
            scenario_name
        ]
