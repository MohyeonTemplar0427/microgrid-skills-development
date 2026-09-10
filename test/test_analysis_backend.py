"""Backend tests for the guided analysis workflow.

Horizons, carbon-weight expansion and the no-battery contract. Nothing here
contacts a live API.
"""

import pandas as pd
import pytest

from src.analysis.carbon_weights import (
    CarbonWeightError,
    build_scenario_name,
    build_scenario_names,
    expand_carbon_weights,
    format_carbon_weight,
)
from src.analysis.no_battery import (
    NO_BATTERY_USAGE_METRICS,
    NoBatteryContractError,
    battery_parameters_are_required,
    create_no_battery_dispatch,
    no_battery_cost_metrics,
    no_battery_usage_metrics,
    validate_no_battery_dispatch,
)
from src.signal_pipeline.horizon import (
    align_to_horizon,
    build_horizon,
    combine_chunks_strictly,
)
from src.signal_pipeline.providers.base import (
    DuplicateIntervalError,
    MissingIntervalError,
)

PACIFIC = "America/Los_Angeles"
EASTERN = "America/New_York"


## Requirement 4: day-based horizon ---------------------------------------


def test_horizon_is_half_open_and_timezone_aware():
    horizon = build_horizon("2026-08-25", 2, PACIFIC)

    assert horizon.start == pd.Timestamp("2026-08-25 00:00", tz=PACIFIC)
    assert horizon.end == pd.Timestamp("2026-08-27 00:00", tz=PACIFIC)

    # start is included, end is excluded.
    assert horizon.index[0] == horizon.start
    assert horizon.end not in horizon.index
    assert horizon.index[-1] == horizon.end - pd.Timedelta(minutes=15)


def test_normal_day_has_96_intervals():
    horizon = build_horizon("2026-08-25", 1, PACIFIC)

    assert horizon.interval_count == 96
    assert horizon.contains_dst_transition() is False


def test_spring_forward_day_has_92_intervals():
    """A 23-hour local day. The count comes from the index, not 1 x 96."""

    horizon = build_horizon("2026-03-08", 1, EASTERN)

    assert horizon.interval_count == 92
    assert horizon.contains_dst_transition() is True


def test_fall_back_day_has_100_intervals():
    """A 25-hour local day."""

    horizon = build_horizon("2026-11-01", 1, EASTERN)

    assert horizon.interval_count == 100
    assert horizon.contains_dst_transition() is True


def test_horizon_spanning_a_dst_transition_is_not_days_times_96():
    horizon = build_horizon("2026-03-07", 3, EASTERN)

    assert horizon.interval_count == 3 * 96 - 4
    assert horizon.interval_count != 3 * 96


def test_horizon_honours_a_non_default_timestep():
    horizon = build_horizon("2026-08-25", 1, PACIFIC, timestep_minutes=60)

    assert horizon.interval_count == 24
    assert horizon.timestep_hours == 1.0


def test_horizon_rejects_a_timestep_that_does_not_divide_a_day():
    with pytest.raises(ValueError):
        build_horizon("2026-08-25", 1, PACIFIC, timestep_minutes=7)


def test_horizon_rejects_nonpositive_days():
    with pytest.raises(ValueError):
        build_horizon("2026-08-25", 0, PACIFIC)


def test_horizon_rejects_an_unknown_timezone():
    with pytest.raises(Exception):
        build_horizon("2026-08-25", 1, "Mars/Olympus_Mons")


def test_align_to_horizon_detects_missing_intervals():
    horizon = build_horizon("2026-08-25", 1, PACIFIC)

    data = pd.DataFrame(
        {
            "timestamp": horizon.index.delete(10),
            "value": 1.0,
        }
    )

    with pytest.raises(MissingIntervalError):
        align_to_horizon(data, horizon, label="Test")


def test_align_to_horizon_rejects_duplicates():
    horizon = build_horizon("2026-08-25", 1, PACIFIC)

    timestamps = horizon.index.append(horizon.index[[5]])

    data = pd.DataFrame(
        {
            "timestamp": timestamps.sort_values(),
            "value": 1.0,
        }
    )

    with pytest.raises(DuplicateIntervalError):
        align_to_horizon(data, horizon, label="Test")


def test_align_to_horizon_clips_rows_outside_the_window():
    horizon = build_horizon("2026-08-25", 1, PACIFIC)

    wider = pd.date_range(
        horizon.start - pd.Timedelta(hours=2),
        horizon.end + pd.Timedelta(hours=2),
        freq="15min",
    )

    data = pd.DataFrame({"timestamp": wider, "value": 1.0})

    aligned = align_to_horizon(data, horizon, label="Test")

    assert len(aligned) == horizon.interval_count
    assert aligned["timestamp"].iloc[0] == horizon.start
    assert aligned["timestamp"].iloc[-1] < horizon.end


## Chunk joining ----------------------------------------------------------


def test_combine_chunks_drops_identical_boundary_rows():
    first = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                pd.Timestamp("2026-08-25 00:00", tz=PACIFIC),
                periods=4,
                freq="15min",
            ),
            "price_per_kWh": [0.01, 0.02, 0.03, 0.04],
        }
    )

    second = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                pd.Timestamp("2026-08-25 00:45", tz=PACIFIC),
                periods=3,
                freq="15min",
            ),
            "price_per_kWh": [0.04, 0.05, 0.06],
        }
    )

    combined = combine_chunks_strictly(
        [first, second],
        value_columns=("price_per_kWh",),
        label="Price",
    )

    assert len(combined) == 6
    assert combined["timestamp"].is_unique
    assert combined["timestamp"].is_monotonic_increasing


def test_combine_chunks_rejects_conflicting_duplicate_values():
    """The same interval returned with two different prices is an error."""

    first = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                pd.Timestamp("2026-08-25 00:00", tz=PACIFIC),
                periods=2,
                freq="15min",
            ),
            "price_per_kWh": [0.01, 0.02],
        }
    )

    second = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                pd.Timestamp("2026-08-25 00:15", tz=PACIFIC),
                periods=2,
                freq="15min",
            ),
            "price_per_kWh": [0.99, 0.03],
        }
    )

    with pytest.raises(ValueError) as error:
        combine_chunks_strictly(
            [first, second],
            value_columns=("price_per_kWh",),
            label="Price",
        )

    assert "disagree" in str(error.value)


## Requirement 5: carbon-weight expansion ---------------------------------


def test_single_carbon_weight():
    assert expand_carbon_weights("single", value=0.2) == (0.2,)


def test_explicit_carbon_weight_list():
    weights = expand_carbon_weights("list", values=[0.0, 0.2, 0.5])

    assert weights == (0.0, 0.2, 0.5)


def test_carbon_weight_list_deduplicates_and_keeps_order():
    weights = expand_carbon_weights("list", values=[0.5, 0.0, 0.5, 0.2])

    assert weights == (0.5, 0.0, 0.2)


def test_inclusive_range_lands_exactly_on_the_end():
    weights = expand_carbon_weights(
        "range", start=0.0, end=1.0, interval=0.1
    )

    assert len(weights) == 11
    assert weights[0] == 0.0
    assert weights[-1] == 1.0
    # 0.1 accumulated in binary floating point drifts; Decimal does not.
    assert weights[3] == 0.3


def test_inclusive_range_of_a_single_point():
    assert expand_carbon_weights(
        "range", start=0.5, end=0.5, interval=0.1
    ) == (0.5,)


def test_range_that_does_not_land_on_the_end_is_rejected():
    with pytest.raises(CarbonWeightError) as error:
        expand_carbon_weights("range", start=0.0, end=1.0, interval=0.3)

    assert "does not land exactly" in str(error.value)


def test_range_rejects_nonpositive_interval():
    with pytest.raises(CarbonWeightError):
        expand_carbon_weights("range", start=0.0, end=1.0, interval=0.0)

    with pytest.raises(CarbonWeightError):
        expand_carbon_weights("range", start=0.0, end=1.0, interval=-0.1)


def test_range_rejects_end_below_start():
    with pytest.raises(CarbonWeightError):
        expand_carbon_weights("range", start=1.0, end=0.5, interval=0.1)


def test_range_rejects_an_excessive_scenario_count():
    with pytest.raises(CarbonWeightError) as error:
        expand_carbon_weights(
            "range", start=0.0, end=1.0, interval=0.0001
        )

    assert "limit" in str(error.value)


def test_negative_and_non_finite_weights_are_rejected():
    with pytest.raises(CarbonWeightError):
        expand_carbon_weights("single", value=-0.1)

    with pytest.raises(CarbonWeightError):
        expand_carbon_weights("list", values=[0.1, float("nan")])

    with pytest.raises(CarbonWeightError):
        expand_carbon_weights("list", values=[float("inf")])


def test_empty_list_is_rejected():
    with pytest.raises(CarbonWeightError):
        expand_carbon_weights("list", values=[])


def test_unknown_carbon_weight_mode_is_rejected():
    with pytest.raises(CarbonWeightError):
        expand_carbon_weights("sweep", value=0.2)


## Scenario naming --------------------------------------------------------


def test_scenario_names_are_deterministic():
    assert build_scenario_name("combined_optimal", 0.0) == (
        "combined_optimal_0.00"
    )
    assert build_scenario_name("combined_optimal", 0.2) == (
        "combined_optimal_0.20"
    )
    assert build_scenario_name("combined_optimal", 0.5) == (
        "combined_optimal_0.50"
    )


def test_scenario_name_map_covers_every_weight():
    weights = expand_carbon_weights("list", values=[0.0, 0.2, 0.5])

    names = build_scenario_names("combined_optimal", weights)

    assert list(names) == [
        "combined_optimal_0.00",
        "combined_optimal_0.20",
        "combined_optimal_0.50",
    ]
    assert list(names.values()) == [0.0, 0.2, 0.5]


def test_colliding_scenario_names_are_rejected():
    with pytest.raises(CarbonWeightError) as error:
        build_scenario_names("combined_optimal", (0.201, 0.202))

    assert "decimals" in str(error.value)


def test_scenario_names_can_use_more_decimals():
    names = build_scenario_names(
        "combined_optimal", (0.201, 0.202), decimals=3
    )

    assert list(names) == [
        "combined_optimal_0.201",
        "combined_optimal_0.202",
    ]


def test_format_carbon_weight_pads_to_two_decimals():
    assert format_carbon_weight(0.2) == "0.20"
    assert format_carbon_weight(1) == "1.00"


## Requirement 6: no-battery contract -------------------------------------


def make_signal_frame(periods: int = 8) -> pd.DataFrame:
    timestamps = pd.date_range(
        pd.Timestamp("2026-08-25 00:00", tz=PACIFIC),
        periods=periods,
        freq="15min",
    )

    load = pd.Series([10.0] * periods)
    pv = pd.Series([0.0, 0.0, 4.0, 12.0] * (periods // 4))

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": load,
            "pv_kw": pv,
            "net_load_kw": load - pv,
            "price_per_kWh": 0.05,
            "gCO2/kWh": 250.0,
        }
    )


def test_no_battery_dispatch_needs_no_battery_parameters():
    dispatch = create_no_battery_dispatch(make_signal_frame())

    assert (dispatch["battery_charge_kw"] == 0).all()
    assert (dispatch["battery_discharge_kw"] == 0).all()
    assert (dispatch["battery_net_injection_kw"] == 0).all()


def test_no_battery_grid_import_and_export_are_nonnegative():
    dispatch = create_no_battery_dispatch(make_signal_frame())

    assert (dispatch["grid_import_kw"] >= 0).all()
    assert (dispatch["grid_export_kw"] >= 0).all()

    # Surplus PV exports rather than showing as negative import.
    surplus = dispatch["net_load_kw"] < 0
    assert (dispatch.loc[surplus, "grid_import_kw"] == 0).all()
    assert (dispatch.loc[surplus, "grid_export_kw"] > 0).all()


def test_no_battery_net_import_matches_net_load():
    dispatch = create_no_battery_dispatch(make_signal_frame())

    pd.testing.assert_series_equal(
        dispatch["grid_net_import_kw"],
        dispatch["net_load_kw"],
        check_names=False,
    )


def test_no_battery_usage_metrics_are_all_zero():
    metrics = no_battery_usage_metrics()

    assert metrics == NO_BATTERY_USAGE_METRICS
    assert metrics["throughput_kWh"] == 0.0
    assert metrics["equivalent_full_cycles"] == 0.0


def test_no_battery_usage_metrics_returns_a_fresh_copy():
    """Callers must not be able to mutate the shared contract."""

    metrics = no_battery_usage_metrics()
    metrics["throughput_kWh"] = 999.0

    assert NO_BATTERY_USAGE_METRICS["throughput_kWh"] == 0.0


def test_no_battery_degradation_cost_is_zero_regardless_of_rate():
    signals = make_signal_frame()
    dispatch = create_no_battery_dispatch(signals)

    metrics = no_battery_cost_metrics(
        dispatch,
        signals[["timestamp", "price_per_kWh"]],
        signals[["timestamp", "gCO2/kWh"]],
    )

    assert metrics["degradation_cost"] == 0.0
    assert metrics["battery_throughput_kWh"] == 0.0
    assert metrics["equivalent_full_cycles"] == 0.0
    assert metrics["total_operating_cost"] == metrics["cost"]


def test_no_battery_results_do_not_depend_on_battery_inputs():
    """The whole point: user battery values cannot reach this path."""

    signals = make_signal_frame()

    first = create_no_battery_dispatch(signals)
    second = create_no_battery_dispatch(signals)

    pd.testing.assert_frame_equal(first, second)

    # There is no parameter through which a battery value could enter.
    import inspect

    signature = inspect.signature(create_no_battery_dispatch)
    assert "battery" not in " ".join(signature.parameters)


def test_validate_no_battery_dispatch_rejects_battery_operation():
    dispatch = create_no_battery_dispatch(make_signal_frame())
    dispatch.loc[2, "battery_charge_kw"] = 3.0

    with pytest.raises(NoBatteryContractError) as error:
        validate_no_battery_dispatch(dispatch)

    assert "battery_charge_kw" in str(error.value)


def test_no_battery_dispatch_rejects_missing_columns():
    signals = make_signal_frame().drop(columns=["pv_kw"])

    with pytest.raises(NoBatteryContractError):
        create_no_battery_dispatch(signals)


def test_no_battery_dispatch_rejects_empty_data():
    with pytest.raises(NoBatteryContractError):
        create_no_battery_dispatch(make_signal_frame().iloc[0:0])


def test_battery_parameters_are_not_required_for_no_battery_only():
    assert battery_parameters_are_required(("no_battery",)) is False
    assert battery_parameters_are_required(
        ("no_battery", "cost_optimal")
    ) is True
    assert battery_parameters_are_required(("rule_based",)) is True
