"""Tests for the interface-to-analysis adapter."""

from types import SimpleNamespace

import pandas as pd

import src.simulation.interface_analysis as interface_analysis
from src.dispatch.battery import Battery
from src.simulation.interface_analysis import (
    format_comparison_for_display,
    run_integrated_csv_analysis,
)
from src.simulation.model_specifications import MicrogridSpecification


def _comparison() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "scenario": [
                "no_battery",
                "rule_based",
                "cost_optimal",
                "carbon_optimal",
                "combined_optimal",
            ],
            "energy_cost": [10.0, 9.0, 8.0, 8.5, 7.5],
            "degradation_cost": [0.0, 0.1, 0.2, 0.2, 0.3],
            "total_explicit_cost": [10.0, 9.1, 8.2, 8.7, 7.8],
            "emissions_kgCO2": [20.0, 19.0, 18.0, 17.0, 16.0],
            "feasible_intervals": [96] * 5,
            "interval_count": [96] * 5,
        }
    )


def test_run_integrated_csv_analysis_filters_and_names_scenarios(
    monkeypatch,
    tmp_path,
):
    csv_path = tmp_path / "signals.csv"
    pd.DataFrame({"timestamp": ["2026-08-25"]}).to_csv(csv_path, index=False)

    calls = []

    def fake_run(*args, carbon_weight, **kwargs):
        calls.append(carbon_weight)
        return SimpleNamespace(comparison=_comparison())

    monkeypatch.setattr(
        interface_analysis,
        "run_microgrid_timeseries_analysis",
        fake_run,
    )

    specification = MicrogridSpecification(
        battery=Battery(
            capacity_kWh=20,
            energy_kWh=10,
            max_charge_kw=5,
            max_discharge_kw=5,
        ),
        pv_capacity_kw=30,
        load_kw=25,
    )

    result = run_integrated_csv_analysis(
        specification,
        csv_path,
        start_date="2026-08-25",
        number_of_days=1,
        timestep_minutes=15,
        expected_timezone="America/Los_Angeles",
        selected_scenarios=("no_battery", "cost_optimal", "combined_optimal"),
        carbon_weights=(0.1, 0.2),
        degradation_cost_per_kWh=0.03,
    )

    assert calls == [0.1, 0.2]
    assert result.comparison["scenario"].tolist() == [
        "no_battery",
        "cost_optimal",
        "combined_optimal_0.10",
        "combined_optimal_0.20",
    ]


def test_format_comparison_for_display_includes_degradation_cost():
    formatted = format_comparison_for_display(_comparison())

    assert "degradation_cost" in formatted
    assert "combined_optimal" in formatted
