"""Interval framework, load sources and PV sources.

Deterministic fixtures only; no live network access.
"""

import numpy as np
import pandas as pd
import pytest

from src.profiles import (
    BuildingArchetype,
    CSVCapacityFactorPV,
    CSVLoad,
    CSVPowerPV,
    ConstantLoad,
    LoadScaling,
    LoadSourceError,
    MeasuredInverterPV,
    MeasuredLoadAdapter,
    PVSourceError,
    SyntheticLoad,
    SyntheticPV,
    WeatherDerivedPV,
    WeatherDerivedPVConfiguration,
)
from src.timeseries import (
    IntervalTableError,
    MissingDataPolicy,
    PowerUnit,
    build_interval_index,
    build_interval_index_from_days,
    build_normalized_table,
    convert_to_kw,
    from_legacy_columns,
    normalize_any_frame,
    to_legacy_columns,
)

PACIFIC = "America/Los_Angeles"
EASTERN = "America/New_York"


## Interval index ---------------------------------------------------------


def test_inclusive_end_date_includes_the_final_day():
    index = build_interval_index("2026-06-01", "2026-06-03", PACIFIC)

    assert index.interval_count == 3 * 96
    assert index.start == pd.Timestamp("2026-06-01 00:00", tz=PACIFIC)
    # The internal boundary is exclusive, one day past the inclusive date.
    assert index.end == pd.Timestamp("2026-06-04 00:00", tz=PACIFIC)
    assert index.index[-1] == pd.Timestamp("2026-06-03 23:45", tz=PACIFIC)
    assert index.end not in index.index


def test_single_day_inclusive_range():
    index = build_interval_index("2026-06-01", "2026-06-01", PACIFIC)

    assert index.interval_count == 96


def test_spring_forward_day_has_92_intervals():
    index = build_interval_index("2026-03-08", "2026-03-08", EASTERN)

    assert index.interval_count == 92
    assert index.interval_count != 96


def test_fall_back_day_has_100_intervals():
    index = build_interval_index("2026-11-01", "2026-11-01", EASTERN)

    assert index.interval_count == 100


def test_month_level_horizon():
    index = build_interval_index("2026-06-01", "2026-06-30", PACIFIC)

    assert index.interval_count == 30 * 96
    assert index.billing_days == pytest.approx(30.0)


def test_horizon_spanning_two_months():
    index = build_interval_index("2026-06-15", "2026-07-14", PACIFIC)

    assert index.interval_count == 30 * 96


def test_hourly_interval_resolution():
    index = build_interval_index("2026-06-01", "2026-06-01", PACIFIC, 60)

    assert index.interval_count == 24
    assert index.timestep_hours == 1.0


def test_end_before_start_is_rejected():
    with pytest.raises(IntervalTableError):
        build_interval_index("2026-06-03", "2026-06-01", PACIFIC)


def test_timestep_must_divide_a_day():
    with pytest.raises(IntervalTableError):
        build_interval_index("2026-06-01", "2026-06-01", PACIFIC, 7)


def test_day_count_helper_matches_inclusive_form():
    by_days = build_interval_index_from_days("2026-06-01", 3, PACIFIC)
    by_dates = build_interval_index("2026-06-01", "2026-06-03", PACIFIC)

    assert by_days.interval_count == by_dates.interval_count
    assert by_days.end == by_dates.end


## Unit conversion --------------------------------------------------------


def test_power_unit_conversion():
    values = pd.Series([1000.0])

    assert convert_to_kw(values, PowerUnit.W).iloc[0] == pytest.approx(1.0)
    assert convert_to_kw(values, "kW").iloc[0] == pytest.approx(1000.0)
    assert convert_to_kw(values, "MW").iloc[0] == pytest.approx(1_000_000.0)


def test_unknown_unit_is_rejected():
    with pytest.raises(ValueError):
        convert_to_kw(pd.Series([1.0]), "horsepower")


## Normalized table and validation ----------------------------------------


def make_index(days: int = 1):
    return build_interval_index(
        "2026-06-01",
        f"2026-06-{days:02d}",
        PACIFIC,
    )


def test_normalized_table_accepts_scalars_and_series():
    index = make_index()

    table = build_normalized_table(
        index,
        native_load_kw=10.0,
        pv_available_kw=np.zeros(index.interval_count),
        price_per_kWh=0.20,
        carbon_intensity_g_per_kWh=250.0,
    )

    assert len(table.data) == index.interval_count
    assert table.data["native_load_kw"].eq(10.0).all()


def test_normalized_table_applies_and_records_missing_data_policy():
    index = make_index()
    load = pd.DataFrame(
        {
            "timestamp": index.index.delete([10, 11]),
            "load": 10.0,
        }
    )

    table = build_normalized_table(
        index,
        native_load_kw=load,
        pv_available_kw=0.0,
        price_per_kWh=0.20,
        carbon_intensity_g_per_kWh=250.0,
        missing_data_policy=MissingDataPolicy.FORWARD_FILL,
    )

    assert len(table.data) == index.interval_count
    assert table.filled_interval_count == 2
    assert table.contains_filled_data is True


def test_billing_days_count_calendar_dates_across_dst():
    spring = build_interval_index("2026-03-08", "2026-03-08", PACIFIC)
    fall = build_interval_index("2026-11-01", "2026-11-01", PACIFIC)

    assert spring.interval_count == 92
    assert fall.interval_count == 100
    assert spring.billing_days == 1.0
    assert fall.billing_days == 1.0


def test_negative_load_is_rejected():
    index = make_index()

    with pytest.raises(IntervalTableError):
        build_normalized_table(
            index,
            native_load_kw=-5.0,
            pv_available_kw=0.0,
            price_per_kWh=0.2,
            carbon_intensity_g_per_kWh=250.0,
        )


def test_pv_above_rating_is_rejected():
    index = make_index()

    with pytest.raises(IntervalTableError) as error:
        build_normalized_table(
            index,
            native_load_kw=10.0,
            pv_available_kw=500.0,
            price_per_kWh=0.2,
            carbon_intensity_g_per_kWh=250.0,
            rated_pv_capacity_kw=50.0,
        )

    assert "rating" in str(error.value)


def test_naive_timestamps_are_rejected():
    naive = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-06-01", periods=96, freq="15min"),
            "native_load_kw": 10.0,
            "pv_available_kw": 0.0,
            "price_per_kWh": 0.2,
            "carbon_intensity_g_per_kWh": 250.0,
        }
    )

    with pytest.raises(IntervalTableError) as error:
        normalize_any_frame(naive)

    assert "timezone-aware" in str(error.value)


def test_fixed_offset_timezone_is_rejected():
    offset = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-06-01", periods=96, freq="15min", tz="UTC"
            ).tz_convert("Etc/GMT+8"),
            "native_load_kw": 10.0,
            "pv_available_kw": 0.0,
            "price_per_kWh": 0.2,
            "carbon_intensity_g_per_kWh": 250.0,
        }
    )

    with pytest.raises(IntervalTableError) as error:
        normalize_any_frame(offset)

    assert "named IANA timezone" in str(error.value)


def test_duplicate_timestamps_are_rejected():
    index = make_index()
    stamps = index.index.append(index.index[[5]]).sort_values()

    duplicated = pd.DataFrame(
        {
            "timestamp": stamps,
            "native_load_kw": 10.0,
            "pv_available_kw": 0.0,
            "price_per_kWh": 0.2,
            "carbon_intensity_g_per_kWh": 250.0,
        }
    )

    with pytest.raises(IntervalTableError) as error:
        normalize_any_frame(duplicated)

    assert "duplicate" in str(error.value).lower()


## Backward compatibility -------------------------------------------------


def test_legacy_columns_round_trip():
    index = make_index()

    legacy = pd.DataFrame(
        {
            "timestamp": index.index,
            "load_kw": 10.0,
            "pv_kw": 4.0,
            "net_load_kw": 6.0,
            "price_per_kWh": 0.2,
            "gCO2/kWh": 250.0,
        }
    )

    canonical = normalize_any_frame(legacy)

    assert canonical["native_load_kw"].eq(10.0).all()
    assert canonical["pv_available_kw"].eq(4.0).all()
    assert canonical["carbon_intensity_g_per_kWh"].eq(250.0).all()

    back = to_legacy_columns(canonical)

    assert back["load_kw"].eq(10.0).all()
    assert back["pv_kw"].eq(4.0).all()
    assert back["gCO2/kWh"].eq(250.0).all()
    # net_load_kw is derived, not carried.
    assert back["net_load_kw"].eq(6.0).all()


def test_from_legacy_does_not_clobber_canonical_columns():
    frame = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-06-01", tz=PACIFIC)],
            "load_kw": [1.0],
            "native_load_kw": [2.0],
        }
    )

    converted = from_legacy_columns(frame)

    assert converted["native_load_kw"].iloc[0] == 2.0


## Load sources -----------------------------------------------------------


def test_constant_load_fills_every_interval():
    index = make_index()

    values = ConstantLoad(load_kw=12.5).build_load_kw(index)

    assert len(values) == index.interval_count
    assert values.eq(12.5).all()


def test_constant_load_rejects_negative():
    with pytest.raises(LoadSourceError):
        ConstantLoad(load_kw=-1.0)


@pytest.mark.parametrize("archetype", list(BuildingArchetype))
def test_every_archetype_produces_a_positive_profile(archetype):
    index = make_index()

    values = SyntheticLoad(
        archetype=archetype,
        scaling=LoadScaling.PEAK_KW,
        peak_kw=50.0,
    ).build_load_kw(index)

    assert len(values) == index.interval_count
    assert (values >= 0).all()
    assert values.max() == pytest.approx(50.0)


def test_synthetic_load_energy_scaling():
    index = make_index()

    values = SyntheticLoad(
        archetype=BuildingArchetype.OFFICE,
        scaling=LoadScaling.DAILY_ENERGY_KWH,
        daily_energy_kWh=400.0,
    ).build_load_kw(index)

    energy = values.sum() * index.timestep_hours

    assert energy == pytest.approx(400.0, rel=1e-6)


def test_synthetic_load_weekday_and_weekend_differ():
    # 2026-06-01 is a Monday; 2026-06-06 is a Saturday.
    weekday = build_interval_index("2026-06-01", "2026-06-01", PACIFIC)
    weekend = build_interval_index("2026-06-06", "2026-06-06", PACIFIC)

    source = SyntheticLoad(
        archetype=BuildingArchetype.OFFICE,
        peak_kw=100.0,
    )

    weekday_energy = source.build_load_kw(weekday).sum()
    weekend_energy = source.build_load_kw(weekend).sum()

    # An office draws much less at the weekend.
    assert weekend_energy < weekday_energy


def test_synthetic_load_is_reproducible_with_a_seed():
    index = make_index()

    def build():
        return SyntheticLoad(
            archetype=BuildingArchetype.RESIDENTIAL,
            peak_kw=10.0,
            variability_fraction=0.15,
            random_seed=99,
        ).build_load_kw(index)

    pd.testing.assert_series_equal(build(), build())


def test_synthetic_load_is_labelled_synthetic():
    source = SyntheticLoad(
        archetype=BuildingArchetype.RETAIL,
        peak_kw=10.0,
    )

    assert source.is_synthetic is True
    assert "SYNTHETIC" in source.describe()


def test_csv_load_unit_conversion():
    index = make_index()

    data = pd.DataFrame(
        {"timestamp": index.index, "demand": 5000.0}
    )

    values = CSVLoad(
        data=data,
        load_column="demand",
        unit=PowerUnit.W,
    ).build_load_kw(index)

    assert values.eq(5.0).all()


def test_csv_load_rejects_negative_values():
    index = make_index()

    data = pd.DataFrame({"timestamp": index.index, "load_kw": -1.0})

    with pytest.raises(LoadSourceError):
        CSVLoad(data=data).build_load_kw(index)


def test_csv_load_rejects_missing_intervals_by_default():
    index = make_index()

    data = pd.DataFrame(
        {"timestamp": index.index[:-4], "load_kw": 10.0}
    )

    with pytest.raises(IntervalTableError) as error:
        CSVLoad(data=data).build_load_kw(index)

    assert "missing" in str(error.value).lower()


def test_csv_load_reports_filled_intervals_under_an_explicit_policy():
    index = make_index()

    data = pd.DataFrame(
        {"timestamp": index.index.delete([10, 11]), "load_kw": 10.0}
    )

    source = CSVLoad(
        data=data,
        missing_data_policy=MissingDataPolicy.FORWARD_FILL,
    )

    values = source.build_load_kw(index)

    assert len(values) == index.interval_count
    assert source.filled_interval_count == 2
    assert "filled" in source.describe()


def test_csv_load_rejects_unknown_column():
    index = make_index()
    data = pd.DataFrame({"timestamp": index.index, "kw": 1.0})

    with pytest.raises(LoadSourceError) as error:
        CSVLoad(data=data, load_column="load_kw").build_load_kw(index)

    assert "load_kw" in str(error.value)


def test_measured_load_adapter_is_an_unimplemented_extension_point():
    with pytest.raises(NotImplementedError) as error:
        MeasuredLoadAdapter("green_button").build_load_kw(make_index())

    assert "not implemented" in str(error.value)


## PV sources -------------------------------------------------------------


def test_synthetic_pv_is_zero_at_night_and_peaks_at_midday():
    index = make_index()

    values = SyntheticPV(rated_pv_capacity_kw=100.0).build_pv_available_kw(
        index
    )

    frame = pd.DataFrame({"timestamp": index.index, "pv": values})
    hours = frame["timestamp"].dt.hour

    assert frame.loc[hours < 5, "pv"].eq(0).all()
    assert frame.loc[hours == 12, "pv"].max() > 0
    assert values.max() <= 100.0
    assert SyntheticPV(rated_pv_capacity_kw=10.0).is_synthetic is True


def test_synthetic_pv_rejects_nonpositive_rating():
    with pytest.raises(PVSourceError):
        SyntheticPV(rated_pv_capacity_kw=0.0)


def test_csv_pv_power_unit_conversion():
    index = make_index()

    data = pd.DataFrame({"timestamp": index.index, "pv_mw": 0.05})

    values = CSVPowerPV(
        data=data,
        pv_column="pv_mw",
        unit=PowerUnit.MW,
    ).build_pv_available_kw(index)

    assert values.eq(50.0).all()


def test_csv_capacity_factor_scales_by_rating():
    index = make_index()

    data = pd.DataFrame(
        {"timestamp": index.index, "capacity_factor": 0.4}
    )

    values = CSVCapacityFactorPV(
        data=data,
        rated_pv_capacity_kw=100.0,
    ).build_pv_available_kw(index)

    assert values.eq(40.0).all()


def test_capacity_factor_above_one_is_rejected():
    index = make_index()

    data = pd.DataFrame(
        {"timestamp": index.index, "capacity_factor": 45.0}
    )

    with pytest.raises(PVSourceError) as error:
        CSVCapacityFactorPV(
            data=data,
            rated_pv_capacity_kw=100.0,
        ).build_pv_available_kw(index)

    assert "capacity factor" in str(error.value).lower()


def test_negative_capacity_factor_is_rejected():
    index = make_index()
    data = pd.DataFrame({"timestamp": index.index, "capacity_factor": -0.1})

    with pytest.raises(PVSourceError):
        CSVCapacityFactorPV(
            data=data, rated_pv_capacity_kw=10.0
        ).build_pv_available_kw(index)


def test_weather_configuration_validates_azimuth_convention():
    # 180 degrees is south under the documented convention.
    configuration = WeatherDerivedPVConfiguration(
        latitude=37.77,
        longitude=-122.42,
        rated_pv_capacity_kw=100.0,
        azimuth_degrees=180.0,
    )

    assert configuration.azimuth_degrees == 180.0

    with pytest.raises(PVSourceError):
        WeatherDerivedPVConfiguration(
            latitude=37.77,
            longitude=-122.42,
            rated_pv_capacity_kw=100.0,
            azimuth_degrees=400.0,
        )

    with pytest.raises(PVSourceError):
        WeatherDerivedPVConfiguration(
            latitude=95.0,
            longitude=0.0,
            rated_pv_capacity_kw=1.0,
        )


def test_weather_derived_pv_is_an_unimplemented_extension_point():
    configuration = WeatherDerivedPVConfiguration(
        latitude=37.77,
        longitude=-122.42,
        rated_pv_capacity_kw=100.0,
    )

    with pytest.raises(NotImplementedError) as error:
        WeatherDerivedPV(configuration).build_pv_available_kw(make_index())

    assert "not implemented" in str(error.value)


def test_measured_inverter_pv_is_an_unimplemented_extension_point():
    with pytest.raises(NotImplementedError):
        MeasuredInverterPV().build_pv_available_kw(make_index())
