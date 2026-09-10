"""Tests for the interactive microgrid console."""

from unittest.mock import Mock

import src.simulation.console_interface as console_interface
from src.simulation.console_interface import (
    _prompt_float,
    prompt_microgrid_specification,
    run_console_snapshot,
)


def test_prompt_float_returns_valid_bounded_value(
    monkeypatch,
):
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "5",
    )

    value = _prompt_float(
        "Enter value: ",
        minimum=0.0,
        maximum=10.0,
    )

    assert value == 5.0


def test_prompt_float_retries_until_value_is_valid(
    monkeypatch,
    capsys,
):
    responses = iter(
        [
            "abc",
            "inf",
            "-1",
            "11",
            "5",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(responses),
    )

    value = _prompt_float(
        "Enter value: ",
        minimum=0.0,
        maximum=10.0,
    )

    captured = capsys.readouterr()

    assert value == 5.0
    assert "Enter a valid number." in captured.out
    assert "Enter a finite number." in captured.out
    assert "greater than or equal to 0.0" in captured.out
    assert "less than or equal to 10.0" in captured.out


def test_prompt_microgrid_specification_builds_model(
    monkeypatch,
):
    responses = iter(
        [
            "20",
            "10",
            "5",
            "6",
            "30",
            "25",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(responses),
    )

    specification = (
        prompt_microgrid_specification()
    )

    assert specification.battery.capacity_kWh == 20.0
    assert specification.battery.energy_kWh == 10.0
    assert specification.battery.max_charge_kw == 5.0
    assert specification.battery.max_discharge_kw == 6.0
    assert specification.pv_capacity_kw == 30.0
    assert specification.load_kw == 25.0


def test_run_console_snapshot_returns_and_prints_results(
    monkeypatch,
    capsys,
):
    responses = iter(
        [
            "20",
            "10",
            "5",
            "5",
            "30",
            "25",
            "10",
            "2",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(responses),
    )

    results = run_console_snapshot()

    captured = capsys.readouterr()

    assert len(results) == 1
    assert bool(results.loc[0, "converged"])
    assert (
        results.loc[
            0,
            "scheduled_grid_import_kw",
        ]
        == 13.0
    )

    assert "=== Simulation Results ===" in captured.out
    assert "Scheduled grid import: 13.0000 kW" in captured.out
    assert "Feasible: True" in captured.out


def test_prompt_microgrid_specification_enforces_energy_bounds(
    monkeypatch,
    capsys,
):
    responses = iter(
        [
            "20",
            "1",
            "19",
            "10",
            "5",
            "5",
            "30",
            "25",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(responses),
    )

    specification = (
        prompt_microgrid_specification()
    )

    captured = capsys.readouterr()

    assert specification.battery.energy_kWh == 10.0
    assert "greater than or equal to 4.0" in captured.out
    assert "less than or equal to 16.0" in captured.out


def test_run_console_snapshot_translates_negative_power_to_charging(
    monkeypatch,
):
    responses = iter(
        [
            "20",
            "10",
            "5",
            "5",
            "30",
            "25",
            "10",
            "-2",
        ]
    )

    monkeypatch.setattr(
        "builtins.input",
        lambda _: next(responses),
    )

    results = run_console_snapshot()

    assert (
        results.loc[
            0,
            "battery_net_injection_kw",
        ]
        == -2.0
    )
    assert (
        results.loc[
            0,
            "scheduled_grid_import_kw",
        ]
        == 17.0
    )


def test_main_runs_console_snapshot(
    monkeypatch,
):
    mock_runner = Mock()

    monkeypatch.setattr(
        console_interface,
        "run_console_snapshot",
        mock_runner,
    )

    console_interface.main()

    mock_runner.assert_called_once_with()
