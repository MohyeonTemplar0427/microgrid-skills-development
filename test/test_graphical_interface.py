"""Tests for the graphical microgrid interface logic."""

from unittest.mock import Mock

import pandas as pd
import pytest

import src.simulation.graphical_interface as graphical_interface
from src.simulation.graphical_interface import (
    _reset_input_entries,
    _run_snapshot_from_entries,
    _set_result_text,
)


class FakeEntry:
    """Imitate the Entry methods used by the GUI helpers."""

    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def delete(self, _start, _end) -> None:
        self.value = ""

    def insert(self, _index, value: str) -> None:
        self.value = value


class FakeText:
    """Imitate the Text methods used by the GUI helpers."""

    def __init__(self) -> None:
        self.value = ""
        self.state = "normal"

    def config(self, *, state: str) -> None:
        self.state = state

    def delete(self, _start, _end) -> None:
        self.value = ""

    def insert(self, _index, value: str) -> None:
        self.value += value


def _make_input_entries(
    battery_net_injection_kw: str = "0",
) -> dict[str, FakeEntry]:
    """Create valid GUI input doubles for one snapshot."""

    return {
        "battery_capacity_kWh": FakeEntry("20"),
        "battery_energy_kWh": FakeEntry("10"),
        "max_charge_kw": FakeEntry("5"),
        "max_discharge_kw": FakeEntry("5"),
        "pv_capacity_kw": FakeEntry("30"),
        "load_kw": FakeEntry("25"),
        "pv_output_kw": FakeEntry("10"),
        "battery_net_injection_kw": FakeEntry(
            battery_net_injection_kw
        ),
    }


def _make_snapshot_result() -> pd.DataFrame:
    """Create the result columns displayed by the GUI."""

    return pd.DataFrame(
        [
            {
                "converged": True,
                "feasible": True,
                "scheduled_grid_import_kw": 15.0,
                "pcc_grid_net_import_kw": 15.0065,
                "pcc_grid_import_kw": 15.0065,
                "pcc_grid_export_kw": 0.0,
                "reverse_power_flow": False,
                "minimum_voltage_pu": 0.998889,
                "maximum_voltage_pu": 0.998889,
                "line_loading_percent": 2.5744,
                "transformer_loading_percent": 2.2830,
                "voltage_violation": False,
                "line_overload": False,
                "transformer_overload": False,
            }
        ]
    )


def test_set_result_text_replaces_content_and_disables_editing():
    result_text = FakeText()
    result_text.value = "Old result"

    _set_result_text(result_text, "New result")

    assert result_text.value == "New result"
    assert result_text.state == "disabled"


def test_reset_input_entries_restores_defaults():
    input_entries = _make_input_entries("4")

    for entry in input_entries.values():
        entry.value = "999"

    _reset_input_entries(input_entries)

    assert {
        name: entry.get()
        for name, entry in input_entries.items()
    } == {
        "battery_capacity_kWh": "20",
        "battery_energy_kWh": "10",
        "max_charge_kw": "5",
        "max_discharge_kw": "5",
        "pv_capacity_kw": "30",
        "load_kw": "25",
        "pv_output_kw": "10",
        "battery_net_injection_kw": "0",
    }


@pytest.mark.parametrize(
    (
        "battery_net_injection_kw",
        "expected_charge_kw",
        "expected_discharge_kw",
    ),
    [
        ("-2", 2.0, 0.0),
        ("2", 0.0, 2.0),
    ],
)
def test_run_snapshot_translates_signed_battery_power(
    monkeypatch,
    battery_net_injection_kw: str,
    expected_charge_kw: float,
    expected_discharge_kw: float,
):
    mock_simulator = Mock(
        return_value=_make_snapshot_result()
    )
    monkeypatch.setattr(
        graphical_interface,
        "simulate_microgrid_snapshot",
        mock_simulator,
    )
    result_text = FakeText()

    _run_snapshot_from_entries(
        _make_input_entries(battery_net_injection_kw),
        result_text,
    )

    specification = mock_simulator.call_args.args[0]
    call_arguments = mock_simulator.call_args.kwargs

    assert specification.battery.capacity_kWh == 20.0
    assert specification.pv_capacity_kw == 30.0
    assert specification.load_kw == 25.0
    assert call_arguments["battery_charge_kw"] == expected_charge_kw
    assert (
        call_arguments["battery_discharge_kw"]
        == expected_discharge_kw
    )
    assert "Converged: True" in result_text.value
    assert "PCC grid export: 0.0000 kW" in result_text.value
    assert "Reverse power flow: False" in result_text.value


def test_run_snapshot_shows_error_for_non_numeric_input(
    monkeypatch,
):
    input_entries = _make_input_entries()
    input_entries["load_kw"].value = "not-a-number"
    mock_showerror = Mock()
    monkeypatch.setattr(
        graphical_interface.messagebox,
        "showerror",
        mock_showerror,
    )

    _run_snapshot_from_entries(
        input_entries,
        FakeText(),
    )

    mock_showerror.assert_called_once()
    assert (
        mock_showerror.call_args.args[0]
        == "Invalid Simulation Input"
    )
