"""Tests for pure logic used by the guided application interface."""

from decimal import Decimal

import pytest

from src.simulation.application_interface import (
    build_review_rows,
    calculate_progress_percentage,
    calculate_inclusive_day_count,
    format_runtime,
    parse_carbon_weights,
    selected_strategies,
)


class FakeBooleanVariable:
    def __init__(self, value: bool) -> None:
        self.value = value

    def get(self) -> bool:
        return self.value


def test_selected_strategies_keeps_display_order():
    values = {
        "no_battery": FakeBooleanVariable(True),
        "rule_based": FakeBooleanVariable(False),
        "cost_optimal": FakeBooleanVariable(True),
        "carbon_optimal": FakeBooleanVariable(False),
        "combined_optimal": FakeBooleanVariable(True),
    }

    assert selected_strategies(values) == (
        "no_battery",
        "cost_optimal",
        "combined_optimal",
    )


def test_build_review_rows_uses_readable_sections_and_units():
    rows = build_review_rows(
        source_mode="live_api",
        region_id="caiso_np15",
        start_date="2026-08-25",
        end_date_inclusive="2026-08-26",
        timestep_minutes="15",
        price_mode="wholesale_market",
        strategies=("no_battery", "cost_optimal"),
        carbon_weights=("0.20",),
        degradation_cost="0.03",
        battery_active=True,
        battery_capacity="20",
        battery_initial_energy="10",
        battery_max_charge="5",
        battery_max_discharge="5",
        pv_capacity="30",
        load_power="25",
    )

    assert rows[0] == ("Analysis", "Data source", "Live APIs")
    assert ("Analysis", "End date (inclusive)", "2026-08-26") in rows
    assert ("Analysis", "Time interval", "15 minutes") in rows
    assert ("Microgrid", "Battery capacity", "20 kWh") in rows


def test_calculate_inclusive_day_count_includes_end_date():
    assert calculate_inclusive_day_count("2026-08-25", "2026-08-31") == 7


def test_calculate_inclusive_day_count_rejects_reversed_range():
    with pytest.raises(ValueError, match="must not precede"):
        calculate_inclusive_day_count("2026-08-31", "2026-08-25")


@pytest.mark.parametrize(
    ("elapsed_seconds", "expected"),
    [
        (12.34, "12.3 seconds"),
        (75.25, "1 min 15.2 sec"),
        (3675.25, "1 hr 1 min 15.2 sec"),
    ],
)
def test_format_runtime_uses_readable_units(elapsed_seconds, expected):
    assert format_runtime(elapsed_seconds) == expected


def test_progress_percentage_advances_left_to_right():
    progress = [
        calculate_progress_percentage(step, 4)
        for step in range(5)
    ]

    assert progress == [5.0, 27.5, 50.0, 72.5, 95.0]
    assert progress == sorted(progress)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("single", [Decimal("0.20")]),
        ("list", [Decimal("0.00"), Decimal("0.10"), Decimal("0.20")]),
        (
            "range",
            [Decimal("0.00"), Decimal("0.10"), Decimal("0.20")],
        ),
    ],
)
def test_parse_carbon_weights(mode, expected):
    assert parse_carbon_weights(
        mode,
        single="0.20",
        explicit_list="0.00, 0.10, 0.20",
        range_start="0.00",
        range_end="0.20",
        range_interval="0.10",
    ) == expected


@pytest.mark.parametrize(
    ("mode", "overrides"),
    [
        ("single", {"single": "-0.1"}),
        ("list", {"explicit_list": "0.1, 0.1"}),
        ("range", {"range_interval": "0"}),
        ("range", {"range_end": "0.25"}),
    ],
)
def test_parse_carbon_weights_rejects_invalid_values(mode, overrides):
    arguments = {
        "single": "0.20",
        "explicit_list": "0.00, 0.10, 0.20",
        "range_start": "0.00",
        "range_end": "0.20",
        "range_interval": "0.10",
    }
    arguments.update(overrides)

    with pytest.raises(ValueError):
        parse_carbon_weights(mode, **arguments)
