import pandas as pd
import pytest

from src.dispatch.results import ExperimentResult
from src.signal_pipeline.market_data_integration import (
    calculate_normalized_kpis,
    calculate_sensitivity_metrics,
    calculate_daily_metrics,
    merge_complete_time_series,
    merge_real_market_data,
    calculate_cost_with_external_price,
    create_real_dispatch_summary,
    validate_integrated_market_data,
    create_market_signal_scenarios,
    create_scenario_comparison_table
)

from src.signal_pipeline.electricity_maps_data import (
    calculate_emissions_with_external_carbon,
)


#Function Implementation ------------------------------------------------
def test_calculate_normalized_kpis():

    result = ExperimentResult(
        no_battery_cost=100.0,
        no_battery_emissions=200.0,

        synthetic_real_cost=0.0,
        synthetic_real_emissions=0.0,

        real_market_cost=90.0,
        real_market_emissions=180.0,

        cost_savings=10.0,
        emissions_reduction=20.0,

        real_market_degradation_cost=4.0,
        real_market_total_operating_cost=94.0,
        operating_cost_savings=6.0,

        synthetic_usage={},
        real_market_usage={
            "equivalent_full_cycles": 2.0,
        },

        weighted_charge_price=0.0,
        weighted_discharge_price=0.0,
        weighted_charge_carbon=0.0,
        weighted_discharge_carbon=0.0,

        daily_summary=pd.DataFrame(),
    )

    kpis = calculate_normalized_kpis(
        result=result,
        number_of_days=4,
    )

    assert kpis[
        "cost_savings_percentage"
    ] == pytest.approx(6.0)

    assert kpis[
        "emissions_reduction_percentage"
    ] == pytest.approx(10.0)

    assert kpis[
        "average_daily_cost_savings"
    ] == pytest.approx(1.5)

    assert kpis[
        "average_daily_emissions_reduction"
    ] == pytest.approx(5.0)

    assert kpis[
        "equivalent_full_cycles_per_day"
    ] == pytest.approx(0.5)


def test_calculate_sensitivity_metrics():

    comparison_table = pd.DataFrame(
        {
            "carbon_weight": [
                0.0,
                0.2,
                0.5,
            ],
            "total_operating_cost": [
                50.0,
                51.0,
                55.0,
            ],
            "emissions_reduction": [
                2.0,
                4.0,
                8.0,
            ],
            "battery_throughput_kWh": [
                10.0,
                20.0,
                40.0,
            ],
            "equivalent_full_cycles": [
                0.5,
                1.0,
                2.0,
            ],
        }
    )

    result = calculate_sensitivity_metrics(
        comparison_table
    )
    assert result.loc[
        1,
        "change_in_operating_cost"
    ] == pytest.approx(1.0)

    assert result.loc[
        1,
        "additional_emissions_reduction"
    ] == pytest.approx(2.0)

    assert result.loc[
        1,
        "additional_throughput_kWh"
    ] == pytest.approx(10.0)

    assert result.loc[
        1,
        "additional_EFC"
    ] == pytest.approx(0.5)

    assert result.loc[
        1,
        "extra_throughput_per_kgCO2"
    ] == pytest.approx(5.0)

    assert result.loc[
        1,
        "marginal_cost_per_kgCO2"
    ] == pytest.approx(0.5)

    assert result.loc[
        2,
        "change_in_operating_cost"
    ] == pytest.approx(4.0)

    assert result.loc[
        2,
        "additional_emissions_reduction"
    ] == pytest.approx(4.0)

    assert result.loc[
        2,
        "additional_throughput_kWh"
    ] == pytest.approx(20.0)

    assert result.loc[
        2,
        "marginal_cost_per_kgCO2"
    ] == pytest.approx(1.0)

    assert pd.isna(
        result.loc[
            0,
            "change_in_operating_cost"
        ]
    )

def test_calculate_daily_metrics():

    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=4,
        freq="15min",
        tz="America/Los_Angeles",
    )

    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "grid_import_kw": [
                4.0,
                4.0,
                4.0,
                4.0,
            ],
            "price_per_kWh": [
                0.10,
                0.10,
                0.10,
                0.10,
            ],
            "gCO2/kWh": [
                200.0,
                200.0,
                200.0,
                200.0,
            ],
            "battery_charge_kw": [
                2.0,
                2.0,
                0.0,
                0.0,
            ],
            "battery_discharge_kw": [
                0.0,
                0.0,
                1.0,
                1.0,
            ],
        }
    )

    result = calculate_daily_metrics(
        data=data,
        degradation_cost_per_kWh=0.03,
        timestep_hours=0.25,
    )

    assert len(result) == 1

    assert result.loc[
        0,
        "grid_import_kWh"
    ] == pytest.approx(4.0)

    assert result.loc[
        0,
        "grid_cost"
    ] == pytest.approx(0.40)

    assert result.loc[
        0,
        "emissions_kgCO2"
    ] == pytest.approx(0.8)

    assert result.loc[
        0,
        "charge_kWh"
    ] == pytest.approx(1.0)

    assert result.loc[
        0,
        "discharge_kWh"
    ] == pytest.approx(0.5)

    assert result.loc[
        0,
        "throughput_kWh"
    ] == pytest.approx(1.5)

    assert result.loc[
        0,
        "degradation_cost"
    ] == pytest.approx(0.045)



def test_merge_complete_time_series_rejects_duplicate_timestamps():
    timestamp = pd.Timestamp(
        "2026-08-25 00:00",
        tz="America/Los_Angeles",
    )

    left_data = pd.DataFrame(
        {
            "timestamp": [
                timestamp,
                timestamp + pd.Timedelta(minutes=15),
            ],
            "load_kw": [
                4.0,
                5.0,
            ],
        }
    )

    right_data = pd.DataFrame(
        {
            "timestamp": [
                timestamp,
                timestamp,
            ],
            "price_per_kWh": [
                0.10,
                0.20,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="Price merge requires unique timestamps",
    ):
        merge_complete_time_series(
            left_data,
            right_data,
            right_name="Price",
        )




def test_merge_complete_time_series_rejects_missing_interval():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=3,
        freq="15min",
        tz="America/Los_Angeles",
    )

    left_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [
                4.0,
                5.0,
                6.0,
            ],
        }
    )

    right_data = pd.DataFrame(
        {
            "timestamp": timestamps[:2],
            "price_per_kWh": [
                0.10,
                0.20,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="does not cover exactly the same timestamps",
    ):
        merge_complete_time_series(
            left_data,
            right_data,
            right_name="Price",
        )


def test_merge_real_market_data_uses_external_market_signals():
    timestamps = pd.date_range(
            start="2026-08-25 00:00",
            periods=2,
            freq="15min",
            tz="America/Los_Angeles",
    )

    synthetic_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [5.0, 6.0],
            "pv_kw": [1.0, 2.0],
            "net_load_kw": [4.0, 4.0],
            "price_per_kWh": [0.10, 0.10],
            "gCO2/kWh": [500.0, 500.0],
        }
    )

    price_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_per_kWh": [0.20, 0.30],
        }
    )

    carbon_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "gCO2/kWh": [100.0, 200.0],
        }
    )

    result = merge_real_market_data(
        synthetic_data,
        price_data,
        carbon_data,
    )

    assert len(result) == 2

    assert result["price_per_kWh"].tolist() == [
        0.20,
        0.30,
    ]

    assert result["gCO2/kWh"].tolist() == [
        100.0,
        200.0,
    ]


def test_calculate_cost_rejects_incomplete_price_coverage():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=3,
        freq="15min",
        tz="America/Los_Angeles",
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "grid_import_kw": [
                4.0,
                4.0,
                4.0,
            ],
        }
    )

    price_data = pd.DataFrame(
        {
            "timestamp": timestamps[:2],
            "price_per_kWh": [
                0.10,
                0.20,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="Price data does not cover exactly the same timestamps",
    ):
        calculate_cost_with_external_price(
            dispatch_data,
            price_data,
            timestep_hours=0.25,
        )

def test_dispatch_summary_rejects_missing_market_interval():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=3,
        freq="15min",
        tz="America/Los_Angeles",
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "battery_charge_kw": [
                2.0,
                0.0,
                0.0,
            ],
            "battery_discharge_kw": [
                0.0,
                1.0,
                1.0,
            ],
        }
    )

    market_data = pd.DataFrame(
        {
            "timestamp": timestamps[:2],
            "price_per_kWh": [
                0.10,
                0.20,
            ],
            "gCO2/kWh": [
                100.0,
                200.0,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match=(
            "Market signal data does not cover exactly "
            "the same timestamps"
        ),
    ):
        create_real_dispatch_summary(
            dispatch_data,
            market_data,
        )


def test_validate_integrated_market_data_rejects_timezone_naive_timestamps():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=2,
        freq="15min",
        tz="America/Los_Angeles",
    )

    data = pd.DataFrame(
        {
            "timestamp": timestamps.tz_localize(None),
            "load_kw": [5.0, 6.0],
            "pv_kw": [1.0, 2.0],
            "net_load_kw": [4.0, 4.0],
            "price_per_kWh": [0.10, 0.20],
            "gCO2/kWh": [100.0, 200.0],
        }
    )

    with pytest.raises(
        ValueError,
        match="Timestamps must be timezone-aware",
    ):
        validate_integrated_market_data(
            data,
            expected_rows=2,
        )



def test_validate_integrated_market_data_rejects_wrong_timezone():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=2,
        freq="15min",
        tz="America/Los_Angeles",
    ).tz_convert("UTC")

    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [5.0, 6.0],
            "pv_kw": [1.0, 2.0],
            "net_load_kw": [4.0, 4.0],
            "price_per_kWh": [0.10, 0.20],
            "gCO2/kWh": [100.0, 200.0],
        }
    )

    with pytest.raises(
        ValueError,
        match=(
            "Expected timezone America/Los_Angeles, "
            "but received UTC"
        ),
    ):
        validate_integrated_market_data(
            data,
            expected_rows=2,
        )


def test_validate_integrated_market_data_rejects_infinite_price():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=2,
        freq="15min",
        tz="America/Los_Angeles",
    )

    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [5.0, 6.0],
            "pv_kw": [1.0, 2.0],
            "net_load_kw": [4.0, 4.0],
            "price_per_kWh": [
                0.10,
                float("inf"),
            ],
            "gCO2/kWh": [100.0, 200.0],
        }
    )

    with pytest.raises(
        ValueError,
        match="contains non-finite numeric values",
    ):
        validate_integrated_market_data(
            data,
            expected_rows=2,
        )

def test_validate_integrated_market_data_rejects_nonnumeric_value():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=2,
        freq="15min",
        tz="America/Los_Angeles",
    )

    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [
                5.0,
                "unknown",
            ],
            "pv_kw": [1.0, 2.0],
            "net_load_kw": [4.0, 4.0],
            "price_per_kWh": [0.10, 0.20],
            "gCO2/kWh": [100.0, 200.0],
        }
    )

    with pytest.raises(
        ValueError,
        match="contains nonnumeric values",
    ):
        validate_integrated_market_data(
            data,
            expected_rows=2,
        )

def test_emissions_reject_incomplete_carbon_coverage():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=3,
        freq="15min",
        tz="America/Los_Angeles",
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "grid_import_kw": [
                4.0,
                4.0,
                4.0,
            ],
        }
    )

    carbon_data = pd.DataFrame(
        {
            "timestamp": timestamps[:2],
            "gCO2/kWh": [
                100.0,
                200.0,
            ],
        }
    )

    with pytest.raises(
        ValueError,
        match="Carbon data does not cover exactly the same timestamps",
    ):
        calculate_emissions_with_external_carbon(
            dispatch_data,
            carbon_data,
            timestep_hours=0.25,
        )

def test_validate_integrated_market_data_accepts_valid_data():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=4,
        freq="15min",
        tz="America/Los_Angeles",
    )

    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [
                5.0,
                6.0,
                7.0,
                6.0,
            ],
            "pv_kw": [
                0.0,
                1.0,
                2.0,
                1.0,
            ],
            "net_load_kw": [
                5.0,
                5.0,
                5.0,
                5.0,
            ],
            "price_per_kWh": [
                0.10,
                0.20,
                -0.01,
                0.30,
            ],
            "gCO2/kWh": [
                100.0,
                200.0,
                300.0,
                400.0,
            ],
        }
    )

    validate_integrated_market_data(
        data,
        expected_rows=4,
        timestep_minutes=15,
    )


def test_market_signal_scenarios_isolate_price_and_carbon():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=2,
        freq="15min",
        tz="America/Los_Angeles",
    )

    synthetic_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [5.0, 6.0],
            "pv_kw": [1.0, 2.0],
            "net_load_kw": [4.0, 4.0],
            "price_per_kWh": [0.10, 0.11],
            "gCO2/kWh": [500.0, 510.0],
        }
    )

    price_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_per_kWh": [0.20, 0.30],
        }
    )

    carbon_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "gCO2/kWh": [100.0, 200.0],
        }
    )

    scenarios = create_market_signal_scenarios(
        synthetic_data,
        price_data,
        carbon_data,
    )

    assert set(scenarios) == {
        "synthetic",
        "real_price",
        "real_carbon",
        "combined_real",
    }

    pd.testing.assert_series_equal(
        scenarios["real_price"]["price_per_kWh"],
        price_data["price_per_kWh"],
    )

    pd.testing.assert_series_equal(
        scenarios["real_price"]["gCO2/kWh"],
        synthetic_data["gCO2/kWh"],
    )

    pd.testing.assert_series_equal(
        scenarios["real_carbon"]["price_per_kWh"],
        synthetic_data["price_per_kWh"],
    )

    pd.testing.assert_series_equal(
        scenarios["real_carbon"]["gCO2/kWh"],
        carbon_data["gCO2/kWh"],
    )

    pd.testing.assert_series_equal(
        scenarios["combined_real"]["price_per_kWh"],
        price_data["price_per_kWh"],
    )

    pd.testing.assert_series_equal(
        scenarios["combined_real"]["gCO2/kWh"],
        carbon_data["gCO2/kWh"],
    )


def test_create_scenario_comparison_table_uses_common_baseline():
    scenario_metrics = {
        "no_battery": {
            "cost": 100.0,
            "emissions_kgCO2": 200.0,
            "total_operating_cost": 100.0
        },
        "real_price": {
            "cost": 80.0,
            "emissions_kgCO2": 190.0,
            "total_operating_cost": 82.0
        },
        "real_carbon": {
            "cost": 95.0,
            "emissions_kgCO2": 150.0,
            "total_operating_cost": 98.0
        },
        "combined_real": {
            "cost": 85.0,
            "emissions_kgCO2": 160.0,
            "total_operating_cost": 90.0
        },
    }

    result = create_scenario_comparison_table(
        scenario_metrics
    ).set_index("scenario")

    assert result.loc[
        "no_battery",
        "cost_savings",
    ] == pytest.approx(0.0)

    assert result.loc[
        "no_battery",
        "emissions_reduction_kgCO2",
    ] == pytest.approx(0.0)

    assert result.loc[
        "real_price",
        "cost_savings",
    ] == pytest.approx(20.0)

    assert result.loc[
        "real_price",
        "emissions_reduction_kgCO2",
    ] == pytest.approx(10.0)

    assert result.loc[
        "real_carbon",
        "cost_savings",
    ] == pytest.approx(5.0)

    assert result.loc[
        "real_carbon",
        "emissions_reduction_kgCO2",
    ] == pytest.approx(50.0)

    assert result.loc[
        "combined_real",
        "cost_savings",
    ] == pytest.approx(15.0)

    assert result.loc[
        "combined_real",
        "emissions_reduction_kgCO2",
    ] == pytest.approx(40.0)

    assert result.loc[
    "real_price",
    "operating_cost_savings",
    ] == pytest.approx(18.0)

    assert result.loc[
        "real_carbon",
        "operating_cost_savings",
    ] == pytest.approx(2.0)

    assert result.loc[
        "combined_real",
        "operating_cost_savings",
    ] == pytest.approx(10.0)


def test_scenario_comparison_reflects_demand_charge_in_operating_savings():
    # Same shape run_multi_day_experiment now produces once a demand
    # charge rate is configured: "demand_charge_cost" is its own column,
    # already folded into "total_operating_cost".
    scenario_metrics = {
        "no_battery": {
            "cost": 100.0,
            "emissions_kgCO2": 200.0,
            "degradation_cost": 0.0,
            "demand_charge_cost": 50.0,
            "total_operating_cost": 150.0,
        },
        "combined_real": {
            "cost": 85.0,
            "emissions_kgCO2": 160.0,
            "degradation_cost": 0.0,
            "demand_charge_cost": 20.0,
            "total_operating_cost": 105.0,
        },
    }

    result = create_scenario_comparison_table(
        scenario_metrics
    ).set_index("scenario")

    # Raw energy cost only differs by 15 (100 -> 85), but the battery also
    # shaved the monthly peak, cutting the demand charge from 50 to 20. The
    # true operating savings (45) are much larger than the energy-only
    # savings would suggest — this is exactly the number that used to be
    # invisible before demand charges were wired into the reporting.
    assert result.loc[
        "combined_real",
        "cost_savings",
    ] == pytest.approx(15.0)

    assert result.loc[
        "combined_real",
        "operating_cost_savings",
    ] == pytest.approx(45.0)
