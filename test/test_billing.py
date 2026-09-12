"""Tariff, meter-topology and billing tests.

B-10 rates are checked against the values published in the tariff effective
1 March 2026.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.billing import (
    BillingError,
    MeterTopologyError,
    MeterTopologyMode,
    PGE_B10_SECONDARY_BUNDLED,
    TariffError,
    allocate_shared_generation,
    calculate_billing,
    calculate_demand_peak,
    calculate_flat_demand_charge,
    calculate_meter_billing,
    get_tariff,
    individual_meters_topology,
    master_with_submeters_topology,
    shared_generation_topology,
    single_pcc_topology,
    supported_tariffs,
)
from src.billing.meter_topology import ConnectionLocation, UtilityMeter
from src.billing.tariffs import ServiceVoltageClass
from src.timeseries import build_interval_index

PACIFIC = "America/Los_Angeles"

B10 = PGE_B10_SECONDARY_BUNDLED
TARIFFS = {B10.tariff_id: B10}


def rate_at(timestamp: str) -> float:
    index = pd.DatetimeIndex([pd.Timestamp(timestamp, tz=PACIFIC)])
    return float(B10.energy_rates(index).iloc[0])


def period_at(timestamp: str) -> str:
    index = pd.DatetimeIndex([pd.Timestamp(timestamp, tz=PACIFIC)])
    return B10.period_names(index).iloc[0]


## B-10 TOU mapping -------------------------------------------------------


def test_b10_summer_rates():
    # Summer is June 1 - September 30.
    assert rate_at("2026-07-15 17:00") == pytest.approx(0.33947)
    assert rate_at("2026-07-15 16:00") == pytest.approx(0.33947)
    assert rate_at("2026-07-15 20:59") == pytest.approx(0.33947)
    # Part-peak: 2-4 p.m. and 9-11 p.m.
    assert rate_at("2026-07-15 14:00") == pytest.approx(0.27778)
    assert rate_at("2026-07-15 21:00") == pytest.approx(0.27778)
    assert rate_at("2026-07-15 22:59") == pytest.approx(0.27778)
    # Everything else is off-peak.
    assert rate_at("2026-07-15 03:00") == pytest.approx(0.24522)
    assert rate_at("2026-07-15 23:00") == pytest.approx(0.24522)


def test_b10_winter_rates():
    assert rate_at("2026-01-15 17:00") == pytest.approx(0.26321)
    assert rate_at("2026-01-15 03:00") == pytest.approx(0.22773)
    # Winter has no part-peak block.
    assert rate_at("2026-01-15 15:00") == pytest.approx(0.22773)


def test_b10_super_off_peak_only_in_march_april_may():
    for month in ("03", "04", "05"):
        assert rate_at(f"2026-{month}-15 10:00") == pytest.approx(0.19139)

    # Same hour in another winter month is ordinary off-peak.
    assert rate_at("2026-01-15 10:00") == pytest.approx(0.22773)
    assert rate_at("2026-11-15 10:00") == pytest.approx(0.22773)


def test_b10_season_boundaries():
    # Summer starts June 1 and ends September 30.
    assert rate_at("2026-06-01 17:00") == pytest.approx(0.33947)
    assert rate_at("2026-09-30 17:00") == pytest.approx(0.33947)
    assert rate_at("2026-05-31 17:00") == pytest.approx(0.26321)
    assert rate_at("2026-10-01 17:00") == pytest.approx(0.26321)


def test_b10_period_names():
    assert period_at("2026-07-15 17:00") == "summer_peak"
    assert period_at("2026-04-15 10:00") == "winter_super_off_peak"


def test_b10_metadata():
    assert B10.service_voltage_class == ServiceVoltageClass.SECONDARY
    assert B10.version == "2026-03-01"
    assert B10.effective_start == date(2026, 3, 1)
    assert "ELEC_SCHEDS_B-10" in B10.source_url
    assert B10.demand_charges[0].rate_per_kW == pytest.approx(20.50)
    assert B10.daily_customer_charge == pytest.approx(11.36882)


def test_tariff_is_versioned_and_date_checked():
    assert get_tariff(B10.tariff_id, date(2026, 6, 1)) is B10

    with pytest.raises(TariffError) as error:
        get_tariff(B10.tariff_id, date(2025, 1, 1))

    assert "effective" in str(error.value)


def test_unknown_tariff_is_rejected():
    with pytest.raises(TariffError):
        get_tariff("pge_b19")

    assert B10.tariff_id in supported_tariffs()


def test_b19_is_not_registered():
    """B-19's multiple demand components must not be approximated by B-10."""

    assert not any("b19" in name for name in supported_tariffs())


def test_rates_follow_local_wall_clock_across_dst():
    # 2026-03-08 is the spring-forward day; 5 p.m. local is still peak.
    index = pd.DatetimeIndex([pd.Timestamp("2026-03-08 17:00", tz=PACIFIC)])

    assert float(B10.energy_rates(index).iloc[0]) == pytest.approx(0.26321)


## Customer charge --------------------------------------------------------


def test_daily_customer_charge_scales_with_days():
    assert B10.customer_charge_for(1) == pytest.approx(11.36882)
    assert B10.customer_charge_for(30) == pytest.approx(341.0646, rel=1e-9)
    assert B10.customer_charge_for(0) == pytest.approx(0.0)


def test_negative_billing_days_rejected():
    with pytest.raises(TariffError):
        B10.customer_charge_for(-1)


## Demand charge ----------------------------------------------------------


def test_demand_peak_uses_maximum_not_sum():
    imports = np.array([10.0, 50.0, 20.0, 30.0])

    billed, simulated, known = calculate_demand_peak(imports)

    assert billed == pytest.approx(50.0)
    assert simulated == pytest.approx(50.0)
    assert known is False
    # Emphatically not the sum.
    assert billed != pytest.approx(imports.sum())


def test_previous_peak_is_honoured_for_a_partial_period():
    imports = np.array([10.0, 40.0])

    billed, simulated, known = calculate_demand_peak(
        imports,
        previous_peak_kw=75.0,
    )

    assert billed == pytest.approx(75.0)
    assert simulated == pytest.approx(40.0)
    assert known is True


def test_simulated_peak_wins_when_it_exceeds_the_previous_peak():
    billed, simulated, known = calculate_demand_peak(
        np.array([120.0]),
        previous_peak_kw=75.0,
    )

    assert billed == pytest.approx(120.0)
    assert simulated == pytest.approx(120.0)


def test_negative_previous_peak_rejected():
    with pytest.raises(BillingError):
        calculate_demand_peak(np.array([1.0]), previous_peak_kw=-5.0)


## Billing over a horizon -------------------------------------------------


def make_dispatch(start: str, end: str, import_kw: float = 100.0):
    index = build_interval_index(start, end, PACIFIC)

    return index, pd.DataFrame(
        {
            "timestamp": index.index,
            "grid_import_kw": np.full(index.interval_count, import_kw),
            "grid_export_kw": np.zeros(index.interval_count),
        }
    )


def test_full_month_billing():
    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)

    periods = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
    )

    assert len(periods) == 1
    period = periods[0]

    assert period.billing_days == pytest.approx(30.0)
    assert period.customer_charge == pytest.approx(11.36882 * 30)
    # A single maximum-demand charge, not one per interval.
    assert period.demand_charge == pytest.approx(20.50 * 100.0)
    assert period.billed_peak_kw == pytest.approx(100.0)
    assert period.is_partial_period is False
    assert period.import_energy_kWh == pytest.approx(100.0 * 24 * 30)


def test_demand_charge_is_not_summed_over_intervals():
    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)

    periods = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
    )

    naive_sum = 20.50 * 100.0 * index.interval_count

    assert periods[0].demand_charge == pytest.approx(2050.0)
    assert periods[0].demand_charge < naive_sum / 100


def test_multi_month_horizon_bills_each_month_separately():
    index, dispatch = make_dispatch("2026-06-01", "2026-07-31", 100.0)

    periods = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
    )

    assert len(periods) == 2
    assert {period.period_label for period in periods} == {"2026-06", "2026-07"}

    # Each month gets its own demand charge and its own customer charge.
    for period in periods:
        assert period.demand_charge == pytest.approx(20.50 * 100.0)

    assert sum(p.customer_charge for p in periods) == pytest.approx(
        11.36882 * 61
    )


def test_multi_month_demand_uses_each_months_own_peak():
    index = build_interval_index("2026-06-01", "2026-07-31", PACIFIC)

    imports = np.full(index.interval_count, 50.0)
    months = pd.DatetimeIndex(index.index).month.to_numpy()
    imports[months == 7] = 90.0

    dispatch = pd.DataFrame(
        {"timestamp": index.index, "grid_import_kw": imports}
    )

    periods = {
        period.period_label: period
        for period in calculate_meter_billing(
            dispatch,
            B10,
            meter_id="pcc",
            timestep_hours=index.timestep_hours,
        )
    }

    assert periods["2026-06"].billed_peak_kw == pytest.approx(50.0)
    assert periods["2026-07"].billed_peak_kw == pytest.approx(90.0)


def test_previous_peak_applies_only_to_first_period():
    index, dispatch = make_dispatch("2026-03-31", "2026-04-30", 40.0)

    periods = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
        previous_peak_kw=120.0,
    )

    assert periods[0].period_label == "2026-03"
    assert periods[0].billed_peak_kw == pytest.approx(120.0)
    assert periods[1].period_label == "2026-04"
    assert periods[1].billed_peak_kw == pytest.approx(40.0)


def test_previous_peak_can_be_supplied_by_billing_period():
    index, dispatch = make_dispatch("2026-03-31", "2026-04-02", 40.0)

    periods = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
        previous_peak_kw={"2026-03": 80.0, "2026-04": 90.0},
    )

    assert periods[0].billed_peak_kw == pytest.approx(80.0)
    assert periods[1].billed_peak_kw == pytest.approx(90.0)


def test_flat_demand_charge_bills_peak_once_per_month():
    _, dispatch = make_dispatch("2026-03-01", "2026-03-31", 40.0)

    cost = calculate_flat_demand_charge(
        dispatch,
        demand_charge_rate_per_kw=10.0,
    )

    assert cost == pytest.approx(400.0)
    # Emphatically not summed across every interval.
    assert cost != pytest.approx(
        10.0 * dispatch["grid_import_kw"].sum()
    )


def test_flat_demand_charge_zero_rate_short_circuits():
    _, dispatch = make_dispatch("2026-03-01", "2026-03-31", 40.0)

    assert calculate_flat_demand_charge(
        dispatch,
        demand_charge_rate_per_kw=0.0,
    ) == 0.0


def test_flat_demand_charge_zero_rate_skips_timestamp_check():
    # A zero rate should short-circuit before ever looking for a
    # timestamp column, so this succeeds even on data that couldn't
    # otherwise be billed.
    dispatch = pd.DataFrame({"grid_import_kw": [10.0, 20.0]})

    assert calculate_flat_demand_charge(
        dispatch,
        demand_charge_rate_per_kw=0.0,
    ) == 0.0


def test_flat_demand_charge_rejects_negative_rate():
    _, dispatch = make_dispatch("2026-03-01", "2026-03-31", 40.0)

    with pytest.raises(BillingError):
        calculate_flat_demand_charge(
            dispatch,
            demand_charge_rate_per_kw=-5.0,
        )


def test_flat_demand_charge_requires_timestamp_column():
    dispatch = pd.DataFrame({"grid_import_kw": [10.0, 20.0]})

    with pytest.raises(BillingError):
        calculate_flat_demand_charge(
            dispatch,
            demand_charge_rate_per_kw=10.0,
        )


def test_flat_demand_charge_honours_previous_peak_first_month_only():
    _, dispatch = make_dispatch("2026-03-31", "2026-04-02", 40.0)

    cost = calculate_flat_demand_charge(
        dispatch,
        demand_charge_rate_per_kw=10.0,
        previous_peak_kw=90.0,
    )

    # March is billed at the known prior peak (90, since it exceeds the
    # simulated 40); April gets no prior peak, so it's billed at its own
    # simulated peak (40) — previous_peak_kw only ever covers the first
    # represented period.
    assert cost == pytest.approx(10.0 * 90.0 + 10.0 * 40.0)


def test_billing_rejects_tariff_outside_effective_window():
    index, dispatch = make_dispatch("2026-01-01", "2026-01-01", 40.0)

    with pytest.raises(TariffError) as error:
        calculate_meter_billing(
            dispatch,
            B10,
            meter_id="pcc",
            timestep_hours=index.timestep_hours,
        )

    assert "not effective" in str(error.value)


def test_customer_charge_counts_dst_date_as_one_day():
    index, dispatch = make_dispatch("2026-03-08", "2026-03-08", 40.0)

    period = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
    )[0]

    assert index.interval_count == 92
    assert period.billing_days == 1.0
    assert period.customer_charge == pytest.approx(B10.daily_customer_charge)


def test_partial_period_without_previous_peak_is_flagged():
    index, dispatch = make_dispatch("2026-06-01", "2026-06-03", 100.0)

    periods = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
    )

    period = periods[0]

    assert period.is_partial_period is True
    assert period.previous_peak_was_known is False
    assert any("PARTIAL BILLING PERIOD" in w for w in period.warnings)


def test_partial_period_with_previous_peak_uses_it():
    index, dispatch = make_dispatch("2026-06-01", "2026-06-03", 40.0)

    periods = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
        previous_peak_kw=120.0,
    )

    period = periods[0]

    assert period.billed_peak_kw == pytest.approx(120.0)
    assert period.simulated_peak_kw == pytest.approx(40.0)
    assert period.demand_charge == pytest.approx(20.50 * 120.0)
    assert period.previous_peak_was_known is True
    assert period.warnings == ()


def test_export_credit_reduces_the_bill():
    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)
    dispatch["grid_export_kw"] = 10.0

    periods = calculate_meter_billing(
        dispatch,
        B10,
        meter_id="pcc",
        timestep_hours=index.timestep_hours,
        export_price_per_kWh=0.05,
    )

    period = periods[0]
    expected_export_kWh = 10.0 * 24 * 30

    assert period.export_energy_kWh == pytest.approx(expected_export_kWh)
    assert period.export_credit == pytest.approx(expected_export_kWh * 0.05)
    assert period.total_utility_charge == pytest.approx(
        period.customer_charge
        + period.import_energy_charge
        + period.demand_charge
        - period.export_credit
    )


## Meter topologies -------------------------------------------------------


def test_single_pcc_is_one_account():
    topology = single_pcc_topology(B10.tariff_id)

    assert topology.mode == MeterTopologyMode.SINGLE_PCC
    assert topology.utility_account_count == 1
    assert topology.demand_is_aggregate is True


def test_single_pcc_billing():
    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)

    result = calculate_billing(
        dispatch,
        single_pcc_topology(B10.tariff_id),
        TARIFFS,
        timestep_hours=index.timestep_hours,
    )

    assert len(result.periods) == 1
    assert result.customer_charge == pytest.approx(11.36882 * 30)
    assert result.demand_charge == pytest.approx(20.50 * 100.0)
    assert result.total_explicit_operating_cost == pytest.approx(
        result.total_utility_charge
    )


def test_master_meter_bills_one_account_despite_submeters():
    topology = master_with_submeters_topology(B10.tariff_id, submeter_count=4)

    assert topology.utility_account_count == 1
    assert len(topology.submeters) == 4
    assert topology.demand_is_aggregate is True

    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)

    result = calculate_billing(
        dispatch,
        topology,
        TARIFFS,
        timestep_hours=index.timestep_hours,
    )

    # One customer charge, not five.
    assert result.customer_charge == pytest.approx(11.36882 * 30)
    assert any("Submeters" in w for w in result.warnings)


def test_master_meter_demand_is_measured_at_the_master():
    topology = master_with_submeters_topology(B10.tariff_id, submeter_count=4)

    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)

    result = calculate_billing(
        dispatch,
        topology,
        TARIFFS,
        timestep_hours=index.timestep_hours,
    )

    # Aggregate 100 kW, not four submeters of 25 kW each.
    assert result.periods[0].billed_peak_kw == pytest.approx(100.0)


def test_individual_meters_bill_separately():
    topology = individual_meters_topology(
        B10.tariff_id,
        unit_count=4,
        uses_equal_allocation_approximation=True,
    )

    assert topology.utility_account_count == 4
    assert topology.demand_is_aggregate is False

    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)

    result = calculate_billing(
        dispatch,
        topology,
        TARIFFS,
        timestep_hours=index.timestep_hours,
    )

    # Four accounts, four customer charges.
    assert len(result.periods) == 4
    assert result.customer_charge == pytest.approx(11.36882 * 30 * 4)
    # Each meter sees a quarter of the site peak.
    for period in result.periods:
        assert period.billed_peak_kw == pytest.approx(25.0)


def test_equal_allocation_approximation_is_labelled():
    topology = individual_meters_topology(
        B10.tariff_id,
        unit_count=3,
        uses_equal_allocation_approximation=True,
    )

    assert topology.uses_equal_allocation_approximation is True
    assert any(
        "APPROXIMATION" in warning
        for warning in topology.approximation_warnings
    )


def test_individual_meter_billing_requires_data_or_explicit_approximation():
    topology = individual_meters_topology(B10.tariff_id, unit_count=2)
    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)

    with pytest.raises(BillingError) as error:
        calculate_billing(
            dispatch,
            topology,
            TARIFFS,
            timestep_hours=index.timestep_hours,
        )

    assert "meter_dispatches" in str(error.value)


def test_individual_meter_billing_accepts_actual_meter_dispatches():
    topology = individual_meters_topology(B10.tariff_id, unit_count=2)
    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)
    _, unit_1 = make_dispatch("2026-06-01", "2026-06-30", 30.0)
    _, unit_2 = make_dispatch("2026-06-01", "2026-06-30", 70.0)

    result = calculate_billing(
        dispatch,
        topology,
        TARIFFS,
        timestep_hours=index.timestep_hours,
        meter_dispatches={"unit_1": unit_1, "unit_2": unit_2},
    )

    peaks = {period.meter_id: period.billed_peak_kw for period in result.periods}
    assert peaks == pytest.approx({"unit_1": 30.0, "unit_2": 70.0})


def test_individual_meters_need_at_least_two_units():
    with pytest.raises(MeterTopologyError):
        individual_meters_topology(B10.tariff_id, unit_count=1)


def test_commercial_tariff_is_not_forced_onto_residential_meters():
    """A meter with no tariff and no default must fail loudly."""

    from src.billing.meter_topology import MeterTopology

    topology = MeterTopology(
        mode=MeterTopologyMode.SINGLE_PCC,
        meters=(UtilityMeter(meter_id="unit_1"),),
    )

    with pytest.raises(MeterTopologyError) as error:
        topology.tariff_for(topology.meters[0])

    assert "residential" in str(error.value)


## Shared generation ------------------------------------------------------


def test_shared_generation_allocation_must_total_100_percent():
    with pytest.raises(MeterTopologyError) as error:
        shared_generation_topology(
            B10.tariff_id,
            unit_count=2,
            allocation_percentages={"unit_1": 50.0, "unit_2": 30.0},
        )

    assert "100%" in str(error.value)


def test_shared_generation_allocation_splits_credit():
    topology = shared_generation_topology(
        B10.tariff_id,
        unit_count=2,
        allocation_percentages={"unit_1": 60.0, "unit_2": 40.0},
    )

    allocations = allocate_shared_generation(1000.0, topology)

    assert allocations["unit_1"] == pytest.approx(600.0)
    assert allocations["unit_2"] == pytest.approx(400.0)
    assert sum(allocations.values()) == pytest.approx(1000.0)


def test_shared_generation_with_common_area():
    topology = shared_generation_topology(
        B10.tariff_id,
        unit_count=2,
        allocation_percentages={
            "unit_1": 45.0,
            "unit_2": 45.0,
            "common_area": 10.0,
        },
        common_area_tariff_id=B10.tariff_id,
    )

    allocations = allocate_shared_generation(500.0, topology)

    assert allocations["common_area"] == pytest.approx(50.0)
    assert topology.has_common_area_meter is True
    assert any(
        "billing credit" in warning
        for warning in topology.approximation_warnings
    )


def test_shared_generation_billing_refuses_unconfigured_credit_rules():
    topology = shared_generation_topology(
        B10.tariff_id,
        unit_count=2,
        allocation_percentages={"unit_1": 50.0, "unit_2": 50.0},
    )
    index, dispatch = make_dispatch("2026-06-01", "2026-06-30", 100.0)

    with pytest.raises(BillingError) as error:
        calculate_billing(
            dispatch,
            topology,
            TARIFFS,
            timestep_hours=index.timestep_hours,
        )

    assert "Shared-generation billing is not implemented" in str(error.value)


## Connection locations ---------------------------------------------------


def test_battery_on_an_unknown_individual_meter_is_rejected():
    from src.billing.meter_topology import MeterTopology

    with pytest.raises(MeterTopologyError) as error:
        MeterTopology(
            mode=MeterTopologyMode.SINGLE_PCC,
            meters=(UtilityMeter(meter_id="pcc", tariff_id=B10.tariff_id),),
            battery_location=ConnectionLocation.INDIVIDUAL_METER,
            battery_meter_id="unit_9",
        )

    assert "unit_9" in str(error.value)


def test_pv_on_a_missing_common_area_meter_is_rejected():
    from src.billing.meter_topology import MeterTopology

    with pytest.raises(MeterTopologyError) as error:
        MeterTopology(
            mode=MeterTopologyMode.SINGLE_PCC,
            meters=(UtilityMeter(meter_id="pcc", tariff_id=B10.tariff_id),),
            pv_location=ConnectionLocation.COMMON_AREA_METER,
        )

    assert "common-area meter" in str(error.value)


def test_billing_result_frame_has_one_row_per_period():
    index, dispatch = make_dispatch("2026-06-01", "2026-07-31", 100.0)

    result = calculate_billing(
        dispatch,
        single_pcc_topology(B10.tariff_id),
        TARIFFS,
        timestep_hours=index.timestep_hours,
        battery_degradation_cost=12.34,
    )

    frame = result.to_frame()

    assert len(frame) == 2
    assert result.battery_degradation_cost == pytest.approx(12.34)
    assert result.total_explicit_operating_cost == pytest.approx(
        result.total_utility_charge + 12.34
    )
