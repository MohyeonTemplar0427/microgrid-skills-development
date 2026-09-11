"""Tests for complete time-series simulation coordination."""

from unittest.mock import Mock

import pandas as pd
import pytest

import src.simulation.time_series_analysis as time_series_analysis
from src.dispatch.battery import Battery
from src.simulation import MicrogridSpecification
from src.simulation.time_series_analysis import (
    TimeSeriesAnalysisResult,
    _normalize_signal_timestamps,
    run_microgrid_timeseries_analysis,
    select_signal_time_range,
)


def _make_specification() -> MicrogridSpecification:
    """Create a valid physical specification for coordinator tests."""

    return MicrogridSpecification(
        battery=Battery(
            capacity_kWh=20.0,
            energy_kWh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
        ),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )


def _make_signal_data() -> pd.DataFrame:
    """Create one nonempty fixed-offset signal interval."""

    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-08-25 00:00:00-07:00"]
            ),
            "load_kw": [25.0],
            "pv_kw": [10.0],
            "net_load_kw": [15.0],
            "price_per_kWh": [0.10],
            "gCO2/kWh": [300.0],
        }
    )


def _make_multi_interval_signal_data() -> pd.DataFrame:
    """Create four consecutive fixed-offset signal intervals."""

    timestamps = pd.date_range(
        "2026-08-25 00:00:00-07:00",
        periods=4,
        freq="15min",
    )

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [20.0, 21.0, 22.0, 23.0],
            "pv_kw": [0.0, 1.0, 2.0, 3.0],
            "net_load_kw": [20.0, 20.0, 20.0, 20.0],
            "price_per_kWh": [0.10, 0.11, 0.12, 0.13],
            "gCO2/kWh": [300.0, 290.0, 280.0, 270.0],
        }
    )


def test_normalize_signal_timestamps_converts_fixed_offset():
    signal_data = _make_signal_data()

    normalized_data = _normalize_signal_timestamps(
        signal_data,
        expected_timezone="America/Los_Angeles",
    )

    assert str(normalized_data["timestamp"].dt.tz) == (
        "America/Los_Angeles"
    )
    assert str(signal_data["timestamp"].dt.tz) == "UTC-07:00"


def test_normalize_signal_timestamps_localizes_naive_time():
    signal_data = _make_signal_data()
    signal_data["timestamp"] = (
        signal_data["timestamp"].dt.tz_localize(None)
    )

    normalized_data = _normalize_signal_timestamps(
        signal_data,
        expected_timezone="America/Los_Angeles",
    )

    assert str(normalized_data["timestamp"].dt.tz) == (
        "America/Los_Angeles"
    )


def test_select_signal_time_range_uses_half_open_interval():
    selected_data = select_signal_time_range(
        _make_multi_interval_signal_data(),
        start_time="2026-08-25 00:15:00",
        end_time="2026-08-25 00:45:00",
    )

    assert len(selected_data) == 2
    assert selected_data.index.tolist() == [0, 1]
    assert selected_data["load_kw"].tolist() == [21.0, 22.0]
    assert selected_data["timestamp"].dt.minute.tolist() == [15, 30]


def test_select_signal_time_range_rejects_reversed_range():
    with pytest.raises(
        ValueError,
        match="start time must be before end time",
    ):
        select_signal_time_range(
            _make_multi_interval_signal_data(),
            start_time="2026-08-25 01:00:00",
            end_time="2026-08-25 00:00:00",
        )


def test_select_signal_time_range_rejects_range_without_data():
    with pytest.raises(
        ValueError,
        match="No signal intervals exist",
    ):
        select_signal_time_range(
            _make_multi_interval_signal_data(),
            start_time="2026-08-26 00:00:00",
            end_time="2026-08-27 00:00:00",
        )


def test_run_timeseries_analysis_coordinates_pipeline(
    monkeypatch,
):
    battery_parameters = {
        "initial_soc_kWh": 10.0,
    }
    dispatch_scenarios = {
        "scenario": pd.DataFrame({"dispatch": [1]}),
    }
    powerflow_scenarios = {
        "scenario": pd.DataFrame({"powerflow": [1]}),
    }
    dispatch_summary = pd.DataFrame(
        {"scenario": ["scenario"]}
    )
    powerflow_summary = pd.DataFrame(
        {"scenario": ["scenario"]}
    )
    comparison = pd.DataFrame(
        {
            "scenario": ["scenario"],
            "energy_cost": [1.0],
        }
    )

    mock_parameter_converter = Mock(
        return_value=battery_parameters
    )
    mock_dispatch_creator = Mock(
        return_value=dispatch_scenarios
    )
    mock_simulator = Mock(
        return_value=powerflow_scenarios
    )
    mock_dispatch_summary = Mock(
        return_value=dispatch_summary
    )
    mock_powerflow_summary = Mock(
        return_value=powerflow_summary
    )
    mock_report_creator = Mock(
        return_value=comparison
    )

    monkeypatch.setattr(
        time_series_analysis,
        "to_optimizer_parameters",
        mock_parameter_converter,
    )
    monkeypatch.setattr(
        time_series_analysis,
        "create_required_dispatch_scenarios",
        mock_dispatch_creator,
    )
    monkeypatch.setattr(
        time_series_analysis,
        "simulate_microgrid_scenarios",
        mock_simulator,
    )
    monkeypatch.setattr(
        time_series_analysis,
        "create_dispatch_performance_summary",
        mock_dispatch_summary,
    )
    monkeypatch.setattr(
        time_series_analysis,
        "create_qsts_scenario_comparison",
        mock_powerflow_summary,
    )
    monkeypatch.setattr(
        time_series_analysis,
        "create_validation_report",
        mock_report_creator,
    )

    specification = _make_specification()

    progress_messages = []

    result = run_microgrid_timeseries_analysis(
        specification,
        _make_signal_data(),
        timestep_minutes=30,
        carbon_weight=0.25,
        degradation_cost_per_kWh=0.04,
        progress_callback=progress_messages.append,
    )

    assert isinstance(result, TimeSeriesAnalysisResult)
    assert result.dispatch_scenarios is dispatch_scenarios
    assert result.powerflow_scenarios is powerflow_scenarios
    assert result.comparison is comparison

    dispatch_call = mock_dispatch_creator.call_args
    normalized_data = dispatch_call.args[0]

    assert str(normalized_data["timestamp"].dt.tz) == (
        "America/Los_Angeles"
    )
    assert dispatch_call.kwargs["carbon_weight"] == 0.25
    assert (
        dispatch_call.kwargs["degradation_cost_per_kWh"]
        == 0.04
    )
    assert dispatch_call.kwargs["time_step_minutes"] == 30
    assert dispatch_call.kwargs["scenario_names"] is None

    metric_call = mock_dispatch_summary.call_args
    assert metric_call.kwargs["timestep_hours"] == 0.5
    assert (
        metric_call.kwargs["degradation_cost_per_kWh"]
        == 0.04
    )

    mock_report_creator.assert_called_once_with(
        dispatch_summary,
        powerflow_summary,
    )
    assert progress_messages == [
        "Optimizing the selected dispatch scenarios",
        "Replaying dispatch through the OpenDSS network",
        "Calculating cost, emissions, and electrical metrics",
    ]


def test_run_timeseries_analysis_selects_requested_range(
    monkeypatch,
):
    selected_data = _make_signal_data()
    mock_range_selector = Mock(
        return_value=selected_data
    )
    mock_dispatch_creator = Mock(
        return_value={"scenario": pd.DataFrame()}
    )

    monkeypatch.setattr(
        time_series_analysis,
        "select_signal_time_range",
        mock_range_selector,
    )
    monkeypatch.setattr(
        time_series_analysis,
        "to_optimizer_parameters",
        Mock(return_value={}),
    )
    monkeypatch.setattr(
        time_series_analysis,
        "create_required_dispatch_scenarios",
        mock_dispatch_creator,
    )
    monkeypatch.setattr(
        time_series_analysis,
        "simulate_microgrid_scenarios",
        Mock(return_value={"scenario": pd.DataFrame()}),
    )
    monkeypatch.setattr(
        time_series_analysis,
        "create_dispatch_performance_summary",
        Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(
        time_series_analysis,
        "create_qsts_scenario_comparison",
        Mock(return_value=pd.DataFrame()),
    )
    monkeypatch.setattr(
        time_series_analysis,
        "create_validation_report",
        Mock(return_value=pd.DataFrame()),
    )

    run_microgrid_timeseries_analysis(
        _make_specification(),
        _make_multi_interval_signal_data(),
        start_time="2026-08-25 00:00:00",
        end_time="2026-08-25 00:30:00",
    )

    mock_range_selector.assert_called_once()
    range_arguments = mock_range_selector.call_args.kwargs
    assert range_arguments["start_time"] == (
        "2026-08-25 00:00:00"
    )
    assert range_arguments["end_time"] == (
        "2026-08-25 00:30:00"
    )
    assert mock_dispatch_creator.call_args.args[0] is selected_data


@pytest.mark.parametrize(
    (
        "start_time",
        "end_time",
    ),
    [
        ("2026-08-25 00:00:00", None),
        (None, "2026-08-26 00:00:00"),
    ],
)
def test_run_timeseries_analysis_rejects_single_boundary(
    start_time: str | None,
    end_time: str | None,
):
    with pytest.raises(
        ValueError,
        match="Both start_time and end_time must be provided",
    ):
        run_microgrid_timeseries_analysis(
            _make_specification(),
            _make_signal_data(),
            start_time=start_time,
            end_time=end_time,
        )


@pytest.mark.parametrize(
    (
        "keyword_arguments",
        "expected_message",
    ),
    [
        (
            {"timestep_minutes": 0},
            "Timestep minutes must be positive",
        ),
        (
            {"carbon_weight": -0.1},
            "Carbon weight must not be negative",
        ),
        (
            {"degradation_cost_per_kWh": -0.1},
            "Degradation cost must not be negative",
        ),
    ],
)
def test_run_timeseries_analysis_rejects_invalid_settings(
    keyword_arguments: dict[str, float],
    expected_message: str,
):
    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        run_microgrid_timeseries_analysis(
            _make_specification(),
            _make_signal_data(),
            **keyword_arguments,
        )


def test_run_timeseries_analysis_rejects_empty_data():
    with pytest.raises(
        ValueError,
        match="signal data must not be empty",
    ):
        run_microgrid_timeseries_analysis(
            _make_specification(),
            pd.DataFrame(),
        )
