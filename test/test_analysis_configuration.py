"""Tests for user-selected time-series analysis settings."""

import pytest

from src.simulation import AnalysisConfiguration


def test_analysis_configuration_calculates_derived_values():
    configuration = AnalysisConfiguration(
        start_date="2026-08-25",
        number_of_days=2,
        region_id="caiso_northern_california",
    )

    assert configuration.end_date == "2026-08-27"
    assert configuration.strategy_count == 5
    assert configuration.timestep_minutes == 15
    assert configuration.carbon_weight == 0.20
    assert configuration.degradation_cost_per_kWh == 0.03


@pytest.mark.parametrize(
    (
        "overrides",
        "expected_message",
    ),
    [
        (
            {"start_date": "08/25/2026"},
            "Start date must use YYYY-MM-DD format",
        ),
        (
            {"number_of_days": 0},
            "Number of days must be positive",
        ),
        (
            {"region_id": "   "},
            "Region ID must not be empty",
        ),
        (
            {"timestep_minutes": 0},
            "Timestep minutes must be positive",
        ),
        (
            {"strategies": ()},
            "At least one strategy must be selected",
        ),
        (
            {
                "strategies": (
                    "no_battery",
                    "no_battery",
                )
            },
            "must not contain duplicates",
        ),
        (
            {
                "strategies": (
                    "no_battery",
                    "unsupported_strategy",
                )
            },
            "Unsupported strategies",
        ),
        (
            {"strategies": ("cost_optimal",)},
            "no-battery baseline must be selected",
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
def test_analysis_configuration_rejects_invalid_settings(
    overrides: dict[str, object],
    expected_message: str,
):
    arguments = {
        "start_date": "2026-08-25",
        "number_of_days": 2,
        "region_id": "caiso_northern_california",
    }
    arguments.update(overrides)

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        AnalysisConfiguration(**arguments)
