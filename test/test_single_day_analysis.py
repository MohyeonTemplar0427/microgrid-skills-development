"""Focused tests for single-day dispatch optimization."""

import pandas as pd
import pytest

from src.single_day_analysis import run_cost_optimization


BATTERY_PARAMETERS = {
    "capacity_kWh": 20.0,
    "initial_soc_kWh": 10.0,
    "min_soc_kWh": 2.0,
    "max_soc_kWh": 18.0,
    "max_charge_kw": 5.0,
    "max_discharge_kw": 5.0,
    "charge_efficiency": 0.95,
    "discharge_efficiency": 0.95,
}


def create_two_interval_price_spread() -> pd.DataFrame:
    """Create a small price-arbitrage case for optimizer tests."""

    return pd.DataFrame(
        {
            "load_kw": [5.0, 5.0],
            "pv_kw": [0.0, 0.0],
            "price_per_kWh": [0.10, 0.20],
        }
    )


def test_cost_optimization_degradation_reduces_throughput():
    data = create_two_interval_price_spread()

    energy_cost_only = run_cost_optimization(
        data.copy(),
        BATTERY_PARAMETERS,
    )

    degradation_aware = run_cost_optimization(
        data.copy(),
        BATTERY_PARAMETERS,
        degradation_cost_per_kWh=0.10,
    )

    energy_cost_only_throughput_kWh = (
        energy_cost_only["battery_charge_kw"].sum()
        + energy_cost_only["battery_discharge_kw"].sum()
    ) * 0.25

    degradation_aware_throughput_kWh = (
        degradation_aware["battery_charge_kw"].sum()
        + degradation_aware["battery_discharge_kw"].sum()
    ) * 0.25

    assert degradation_aware_throughput_kWh < (
        energy_cost_only_throughput_kWh
    )


def test_cost_optimization_rejects_negative_degradation_cost():
    with pytest.raises(
        ValueError,
        match="Degradation cost must not be negative",
    ):
        run_cost_optimization(
            create_two_interval_price_spread(),
            BATTERY_PARAMETERS,
            degradation_cost_per_kWh=-0.01,
        )
