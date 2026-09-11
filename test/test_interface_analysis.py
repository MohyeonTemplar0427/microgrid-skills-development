"""Tests for the interface-to-analysis adapter."""

from types import SimpleNamespace

import pandas as pd
import pytest

import src.simulation.interface_analysis as interface_analysis
from src.dispatch.battery import Battery
from src.simulation.interface_analysis import (
    build_analysis_details,
    build_results_table,
    create_temporary_site_profile,
    format_comparison_for_display,
    run_integrated_csv_analysis,
)
from src.signal_pipeline.horizon import build_horizon
from src.signal_pipeline.price_sources import WholesaleMarketPrice
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
            "equivalent_full_cycles": [0.0, 0.2, 0.3, 0.4, 0.5],
            "average_daily_efc": [0.0, 0.1, 0.15, 0.2, 0.25],
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
    progress_messages = []

    def fake_run(
        *args,
        carbon_weight,
        scenario_names,
        progress_callback,
        **kwargs,
    ):
        calls.append((carbon_weight, scenario_names))
        progress_callback("test backend phase")
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
        progress_callback=progress_messages.append,
    )

    assert calls == [
        (
            0.1,
            ("no_battery", "cost_optimal", "combined_optimal"),
        ),
        (0.2, ("combined_optimal",)),
    ]
    assert result.comparison["scenario"].tolist() == [
        "no_battery",
        "cost_optimal",
        "combined_optimal_0.10",
        "combined_optimal_0.20",
    ]
    assert any(
        "test backend phase" in message
        for message in progress_messages
    )


def test_format_comparison_for_display_includes_degradation_cost():
    formatted = format_comparison_for_display(_comparison())

    assert "degradation_cost" in formatted
    assert "combined_optimal" in formatted


def test_create_temporary_site_profile_uses_configured_ratings():
    horizon = build_horizon(
        "2026-08-25",
        1,
        "America/Los_Angeles",
        15,
    )

    profile = create_temporary_site_profile(
        horizon,
        load_kw=25,
        pv_capacity_kw=30,
    )

    assert len(profile) == 96
    assert profile["load_kw"].eq(25).all()
    assert profile["pv_kw"].min() == 0
    assert profile["pv_kw"].max() == 30


def test_build_results_table_uses_readable_headings():
    comparison = _comparison().copy()
    comparison["pcc_grid_import_energy_kWh"] = 100.12345
    comparison["peak_grid_import_kw"] = 30.12345
    comparison["minimum_voltage_pu"] = 0.998123
    comparison["maximum_line_loading_percent"] = 4.8
    comparison["maximum_transformer_loading_percent"] = 4.2

    headings, rows = build_results_table(comparison)

    assert headings[0] == "Scenario"
    assert "Degradation ($)" in headings
    assert "Avg daily EFC" in headings
    assert "Feasible intervals" not in headings
    assert rows[0][0] == "no_battery"
    assert rows[0][1] == "10.00"


def test_build_analysis_details_describes_live_study_horizon():
    details = dict(
        build_analysis_details(
            source_mode="live_api",
            region_id="caiso_np15",
            market_location="TH_NP15_GEN-APND",
            csv_path="",
            start_date="2026-08-25",
            end_date_inclusive="2026-08-26",
            timestep_minutes=15,
        )
    )

    assert details["Data source"] == "Live APIs"
    assert "Northern California" in details["Location"]
    assert "TH_NP15_GEN-APND" in details["Location"]
    assert details["Time range"] == (
        "2026-08-25 → 2026-08-26 (both dates included)"
    )
    assert details["Time interval"] == "15 minutes"


@pytest.mark.parametrize(
    ("region_id", "expected_timezone"),
    [
        ("ercot_houston_hub", "America/Chicago"),
        ("pjm_western_hub", "America/New_York"),
    ],
)
def test_live_regional_analysis_reaches_opendss_results(
    monkeypatch,
    tmp_path,
    region_id,
    expected_timezone,
):
    def fake_prices(self, horizon):
        return pd.DataFrame(
            {
                "timestamp": horizon.index,
                "price_per_kWh": 0.10,
            }
        )

    def fake_carbon(
        api_key,
        zone,
        start_date,
        number_of_days,
        timezone,
    ):
        horizon = build_horizon(
            start_date,
            number_of_days,
            timezone,
            15,
        )
        return pd.DataFrame(
            {
                "timestamp": horizon.index,
                "gCO2/kWh": 300.0,
            }
        )

    monkeypatch.setattr(
        WholesaleMarketPrice,
        "build_prices",
        fake_prices,
    )
    monkeypatch.setattr(
        "src.signal_pipeline.signal_loader."
        "emd.get_multi_day_carbon_data",
        fake_carbon,
    )
    monkeypatch.setattr(
        interface_analysis,
        "DEFAULT_SIGNAL_CACHE_DIRECTORY",
        tmp_path,
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
    result = interface_analysis.run_live_api_analysis(
        specification,
        start_date="2026-08-25",
        number_of_days=1,
        timestep_minutes=15,
        region_id=region_id,
        market_provider=None,
        market_location=None,
        carbon_provider=None,
        carbon_zone=None,
        timezone=None,
        price_mode="wholesale_market",
        fixed_retail_price=None,
        price_csv_path=None,
        selected_scenarios=("no_battery", "cost_optimal"),
        carbon_weights=(0.20,),
        degradation_cost_per_kWh=0.03,
    )

    assert result.comparison["scenario"].tolist() == [
        "no_battery",
        "cost_optimal",
    ]
    assert all(
        frame["converged"].all()
        for frame in result.runs_by_carbon_weight[
            0.20
        ].powerflow_scenarios.values()
    )
    assert all(
        str(frame["timestamp"].dt.tz) == expected_timezone
        for frame in result.runs_by_carbon_weight[
            0.20
        ].dispatch_scenarios.values()
    )
