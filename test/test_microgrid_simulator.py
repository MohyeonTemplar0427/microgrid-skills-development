"""Tests for the user-facing microgrid simulator."""
import pytest

import pandas as pd

from src.dispatch.battery import Battery

from src.simulation import (
    MicrogridSpecification,
    simulate_microgrid_scenarios,
    simulate_microgrid_snapshot,
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


def test_simulate_microgrid_snapshot_uses_specification():
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

    # Act
    result = simulate_microgrid_snapshot(
        specification,
        timestamp="2026-08-25 12:00:00",
        pv_output_kw=10.0,
        battery_discharge_kw=2.0,
    )

    # Assert
    assert len(result) == 1
    assert bool(result.loc[0, "converged"])
    assert result.loc[0, "load_kw"] == 25.0
    assert result.loc[0, "pv_kw"] == 10.0
    assert (
        result.loc[
            0,
            "battery_net_injection_kw",
        ]
        == 2.0
    )
    assert (
        result.loc[
            0,
            "scheduled_grid_import_kw",
        ]
        == 13.0
    )


def test_simulate_microgrid_snapshot_rejects_negative_discharge():

    specification = MicrogridSpecification(
        battery=Battery(),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    with pytest.raises(
        ValueError,
        match="Battery discharging power must not be negative.",
    ):
        simulate_microgrid_snapshot(
            specification,
            timestamp="2026-08-25 12:00:00",
            pv_output_kw=10.0,
            battery_discharge_kw=-1.0,
        )


@pytest.mark.parametrize(
    (
        "battery_power_kw",
        "expected_message",
    ),
    [
        (
            6.0,
            "discharge-power limit",
        ),
        (
            -6.0,
            "charge-power limit",
        ),
    ],
)
def test_simulate_microgrid_scenarios_rejects_excessive_battery_power(
    battery_power_kw: float,
    expected_message: str,
):
    specification = MicrogridSpecification(
        battery=Battery(
            capacity_kWh=20.0,
            SOC_min=0.1,
            SOC_max=0.9,
            energy_kWh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
        ),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-08-25 12:00:00"),
            ],
            "battery_net_injection_kw": [
                battery_power_kw,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        simulate_microgrid_scenarios(
            specification,
            {
                "invalid_scenario": dispatch_data,
            },
        )

@pytest.mark.parametrize(
    (
        "battery_energy_kWh",
        "expected_message",
    ),
    [
        (
            1.0,
            "minimum SOC",
        ),
        (
            19.0,
            "maximum SOC",
        ),
    ],
)
def test_simulate_microgrid_scenarios_rejects_invalid_soc(
    battery_energy_kWh: float,
    expected_message: str,
):
    specification = MicrogridSpecification(
        battery=Battery(
            capacity_kWh=20.0,
            SOC_min=0.1,
            SOC_max=0.9,
            energy_kWh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
        ),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-08-25 12:00:00"),
            ],
            "battery_net_injection_kw": [
                0.0,
            ],
            "battery_soc_kWh": [
                battery_energy_kWh,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        simulate_microgrid_scenarios(
            specification,
            {
                "invalid_scenario": dispatch_data,
            },
        )

@pytest.mark.parametrize(
    (
        "pv_output_kw",
        "expected_message",
    ),
    [
        (
            -1.0,
            "PV output must not be negative",
        ),
        (
            31.0,
            "configured PV capacity",
        ),
    ],
)
def test_simulate_microgrid_scenarios_rejects_invalid_pv_output(
    pv_output_kw: float,
    expected_message: str,
):
    specification = MicrogridSpecification(
        battery=Battery(
            capacity_kWh=20.0,
            SOC_min=0.1,
            SOC_max=0.9,
            energy_kWh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
        ),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-08-25 12:00:00"),
            ],
            "battery_net_injection_kw": [
                0.0,
            ],
            "battery_soc_kWh": [
                10.0,
            ],
            "pv_kw": [
                pv_output_kw,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        simulate_microgrid_scenarios(
            specification,
            {
                "invalid_scenario": dispatch_data,
            },
        )

def test_simulate_microgrid_scenarios_rejects_negative_load():
    specification = MicrogridSpecification(
        battery=Battery(
            capacity_kWh=20.0,
            SOC_min=0.1,
            SOC_max=0.9,
            energy_kWh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
        ),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-08-25 12:00:00"),
            ],
            "battery_net_injection_kw": [
                0.0,
            ],
            "battery_soc_kWh": [
                10.0,
            ],
            "pv_kw": [
                10.0,
            ],
            "load_kw": [
                -1.0,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="Load power must not be negative",
    ):
        simulate_microgrid_scenarios(
            specification,
            {
                "invalid_scenario": dispatch_data,
            },
        )

def test_simulate_microgrid_scenarios_rejects_power_imbalance():
    specification = MicrogridSpecification(
        battery=Battery(
            capacity_kWh=20.0,
            SOC_min=0.1,
            SOC_max=0.9,
            energy_kWh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
        ),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-08-25 12:00:00"),
            ],
            "load_kw": [
                25.0,
            ],
            "pv_kw": [
                10.0,
            ],
            "battery_net_injection_kw": [
                2.0,
            ],
            "battery_soc_kWh": [
                10.0,
            ],
            "grid_net_import_kw": [
                20.0,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="does not satisfy power balance",
    ):
        simulate_microgrid_scenarios(
            specification,
            {
                "invalid_scenario": dispatch_data,
            },
        )


@pytest.mark.parametrize(
    (
        "timestamps",
        "expected_message",
    ),
    [
        (
            [
                "not-a-timestamp",
            ],
            "invalid timestamp",
        ),
        (
            [
                pd.Timestamp("2026-08-25 12:00:00"),
                pd.Timestamp("2026-08-25 12:00:00"),
            ],
            "duplicate timestamps",
        ),
        (
            [
                pd.Timestamp("2026-08-25 12:15:00"),
                pd.Timestamp("2026-08-25 12:00:00"),
            ],
            "in increasing order",
        ),
    ],
)


def test_simulate_microgrid_scenarios_rejects_invalid_timestamps(
    timestamps: list,
    expected_message: str,
):
    dispatch_data = pd.DataFrame(
        {
            "timestamp": timestamps,
        }
    )

    specification = MicrogridSpecification(
        battery=Battery(),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    with pytest.raises(
        ValueError,
        match=expected_message,
    ):
        simulate_microgrid_scenarios(
            specification,
            {
                "invalid_scenario": dispatch_data,
            },
        )

def test_simulate_microgrid_scenarios_rejects_missing_interval():
    dispatch_data = pd.DataFrame(
        {
            "timestamp": [
                pd.Timestamp("2026-08-25 12:00:00"),
                pd.Timestamp("2026-08-25 12:30:00"),
            ],
        }
    )

    specification = MicrogridSpecification(
        battery=Battery(),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    with pytest.raises(
        ValueError,
        match="not continuous 15-minute intervals",
    ):
        simulate_microgrid_scenarios(
            specification,
            {
                "invalid_scenario": dispatch_data,
            },
        )

def test_simulate_microgrid_scenarios_accepts_configured_timestep():
    timestamps = pd.to_datetime(
        [
            "2026-08-25 12:00:00",
            "2026-08-25 12:30:00",
        ]
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [
                25.0,
                25.0,
            ],
            "pv_kw": [
                10.0,
                10.0,
            ],
            "battery_net_injection_kw": [
                0.0,
                0.0,
            ],
            "battery_soc_kWh": [
                10.0,
                10.0,
            ],
            "grid_net_import_kw": [
                15.0,
                15.0,
            ],
        }
    )

    specification = MicrogridSpecification(
        battery=Battery(),
        pv_capacity_kw=30.0,
        load_kw=25.0,
    )

    results = simulate_microgrid_scenarios(
        specification,
        {
            "thirty_minute_scenario": dispatch_data,
        },
        timestep_minutes=30,
    )

    assert len(
        results["thirty_minute_scenario"]
    ) == 2

    assert results[
        "thirty_minute_scenario"
    ]["converged"].all()