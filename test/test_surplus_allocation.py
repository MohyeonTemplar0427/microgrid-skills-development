"""Surplus-PV allocation, power balance and scenario metrics."""

import numpy as np
import pandas as pd
import pytest

from src.surplus import (
    ExportCompensationMode,
    FlexibleLoadCapability,
    GridExportCapability,
    PowerBalanceError,
    SurplusConfiguration,
    SurplusConfigurationError,
    allocate_surplus,
    default_surplus_configuration,
    validate_no_simultaneity,
    validate_power_balance,
)
from src.surplus.metrics import (
    calculate_economic_metrics,
    calculate_energy_metrics,
)
from src.timeseries import build_interval_index

PACIFIC = "America/Los_Angeles"


def make_scenario(days: int = 1):
    """Flat 10 kW load with a 30 kW midday PV surplus."""

    index = build_interval_index(
        "2026-06-01",
        f"2026-06-{days:02d}",
        PACIFIC,
    )

    load = np.full(index.interval_count, 10.0)
    pv = np.zeros(index.interval_count)

    hours = index.index.hour.to_numpy()
    pv[(hours >= 10) & (hours < 16)] = 30.0

    return index, load, pv


## Defaults ---------------------------------------------------------------


def test_default_configuration_disables_export_and_flexible_load():
    configuration = default_surplus_configuration()

    assert configuration.grid_export.enabled is False
    assert configuration.flexible_load.enabled is False
    assert configuration.curtailment_is_only_outlet is True


def test_default_curtails_all_surplus():
    index, load, pv = make_scenario()

    frame = allocate_surplus(index.index, load, pv, default_surplus_configuration())

    validate_power_balance(frame)

    # Surplus is 20 kW for six hours: 120 kWh curtailed.
    curtailed = frame["pv_curtailed_kw"].sum() * index.timestep_hours

    assert curtailed == pytest.approx(120.0)
    assert frame["grid_export_kw"].eq(0).all()
    assert frame["flexible_load_kw"].eq(0).all()


## Export -----------------------------------------------------------------


def test_unlimited_export_curtails_nothing():
    index, load, pv = make_scenario()

    configuration = SurplusConfiguration(
        grid_export=GridExportCapability(enabled=True, limit_kw=None)
    )

    frame = allocate_surplus(index.index, load, pv, configuration)
    validate_power_balance(frame)

    assert frame["pv_curtailed_kw"].sum() == pytest.approx(0.0)
    assert frame["grid_export_kw"].sum() * index.timestep_hours == (
        pytest.approx(120.0)
    )
    assert configuration.grid_export.is_unlimited is True


def test_limited_export_curtails_the_remainder():
    index, load, pv = make_scenario()

    configuration = SurplusConfiguration(
        grid_export=GridExportCapability(enabled=True, limit_kw=5.0)
    )

    frame = allocate_surplus(index.index, load, pv, configuration)
    validate_power_balance(frame)

    hours = index.timestep_hours
    exported = frame["grid_export_kw"].sum() * hours
    curtailed = frame["pv_curtailed_kw"].sum() * hours

    # 5 kW of the 20 kW surplus exports; 15 kW is curtailed.
    assert exported == pytest.approx(30.0)
    assert curtailed == pytest.approx(90.0)
    assert frame["grid_export_kw"].max() <= 5.0 + 1e-9


def test_export_limit_must_be_nonnegative():
    with pytest.raises(SurplusConfigurationError):
        GridExportCapability(enabled=True, limit_kw=-1.0)


def test_tariff_export_compensation_is_not_silently_accepted():
    with pytest.raises(SurplusConfigurationError) as error:
        GridExportCapability(
            enabled=True,
            compensation_mode=ExportCompensationMode.TARIFF,
        )

    assert "not implemented" in str(error.value)


## Flexible load ----------------------------------------------------------


def test_flexible_load_absorbs_surplus_and_rest_is_curtailed():
    index, load, pv = make_scenario()

    configuration = SurplusConfiguration(
        flexible_load=FlexibleLoadCapability(enabled=True, maximum_kw=8.0)
    )

    frame = allocate_surplus(index.index, load, pv, configuration)
    validate_power_balance(frame)

    hours = index.timestep_hours
    flexible = frame["flexible_load_kw"].sum() * hours
    curtailed = frame["pv_curtailed_kw"].sum() * hours

    assert flexible == pytest.approx(48.0)
    assert curtailed == pytest.approx(72.0)
    assert frame["total_load_kw"].max() == pytest.approx(18.0)


def test_export_and_flexible_load_coexist():
    """They are capabilities, not mutually exclusive modes."""

    index, load, pv = make_scenario()

    configuration = SurplusConfiguration(
        grid_export=GridExportCapability(enabled=True, limit_kw=5.0),
        flexible_load=FlexibleLoadCapability(enabled=True, maximum_kw=8.0),
    )

    frame = allocate_surplus(index.index, load, pv, configuration)
    validate_power_balance(frame)

    hours = index.timestep_hours

    assert frame["flexible_load_kw"].sum() * hours == pytest.approx(48.0)
    assert frame["grid_export_kw"].sum() * hours == pytest.approx(30.0)
    assert frame["pv_curtailed_kw"].sum() * hours == pytest.approx(42.0)
    assert configuration.curtailment_is_only_outlet is False


## Power balance across every configuration -------------------------------


@pytest.mark.parametrize(
    "configuration",
    [
        default_surplus_configuration(),
        SurplusConfiguration(
            grid_export=GridExportCapability(enabled=True, limit_kw=None)
        ),
        SurplusConfiguration(
            grid_export=GridExportCapability(enabled=True, limit_kw=5.0)
        ),
        SurplusConfiguration(
            flexible_load=FlexibleLoadCapability(enabled=True, maximum_kw=8.0)
        ),
        SurplusConfiguration(
            grid_export=GridExportCapability(enabled=True, limit_kw=12.0),
            flexible_load=FlexibleLoadCapability(enabled=True, maximum_kw=4.0),
        ),
    ],
)
def test_power_balance_holds_for_every_surplus_configuration(configuration):
    index, load, pv = make_scenario()

    frame = allocate_surplus(index.index, load, pv, configuration)

    validate_power_balance(frame)
    validate_no_simultaneity(frame)


def test_power_balance_holds_with_battery_operation():
    index, load, pv = make_scenario()

    charge = np.zeros(index.interval_count)
    discharge = np.zeros(index.interval_count)

    hours = index.index.hour.to_numpy()
    charge[(hours >= 11) & (hours < 13)] = 6.0
    discharge[(hours >= 18) & (hours < 20)] = 6.0

    frame = allocate_surplus(
        index.index,
        load,
        pv,
        default_surplus_configuration(),
        battery_charge_kw=charge,
        battery_discharge_kw=discharge,
    )

    validate_power_balance(frame)
    validate_no_simultaneity(frame)

    # Charging happens during surplus, so it is attributed to PV.
    assert frame["pv_charging_battery_kw"].sum() > 0
    assert frame["grid_charging_battery_kw"].sum() == pytest.approx(0.0)


def test_grid_charging_is_attributed_separately_from_pv_charging():
    index, load, pv = make_scenario()

    charge = np.zeros(index.interval_count)
    hours = index.index.hour.to_numpy()
    # Charge at 02:00, when no PV is available.
    charge[(hours >= 2) & (hours < 4)] = 5.0

    frame = allocate_surplus(
        index.index,
        load,
        pv,
        default_surplus_configuration(),
        battery_charge_kw=charge,
    )

    validate_power_balance(frame)

    assert frame["pv_charging_battery_kw"].sum() == pytest.approx(0.0)
    assert frame["grid_charging_battery_kw"].sum() > 0


def test_simultaneity_violation_is_detected():
    index, load, pv = make_scenario()

    frame = allocate_surplus(
        index.index, load, pv, default_surplus_configuration()
    )

    frame.loc[5, "battery_charge_kw"] = 4.0
    frame.loc[5, "battery_discharge_kw"] = 3.0

    with pytest.raises(PowerBalanceError) as error:
        validate_no_simultaneity(frame)

    assert "simultaneous" in str(error.value)


def test_broken_balance_is_detected():
    index, load, pv = make_scenario()

    frame = allocate_surplus(
        index.index, load, pv, default_surplus_configuration()
    )

    frame.loc[50, "grid_import_kw"] += 25.0

    with pytest.raises(PowerBalanceError):
        validate_power_balance(frame)


## Metrics ----------------------------------------------------------------


def test_pv_allocation_metrics():
    index, load, pv = make_scenario()

    configuration = SurplusConfiguration(
        grid_export=GridExportCapability(enabled=True, limit_kw=5.0)
    )

    frame = allocate_surplus(index.index, load, pv, configuration)

    metrics = calculate_energy_metrics(
        frame,
        timestep_hours=index.timestep_hours,
    )

    # 30 kW for 6 hours = 180 kWh available.
    assert metrics.available_pv_energy_kWh == pytest.approx(180.0)
    assert metrics.curtailed_pv_energy_kWh == pytest.approx(90.0)
    assert metrics.actual_pv_energy_kWh == pytest.approx(90.0)
    assert metrics.curtailment_percent == pytest.approx(50.0)
    assert metrics.exported_energy_kWh == pytest.approx(30.0)
    # PV serves the 10 kW load for the six sunny hours.
    assert metrics.self_consumed_pv_energy_kWh == pytest.approx(60.0)
    assert metrics.peak_grid_import_kw == pytest.approx(10.0)


def test_export_revenue_and_net_cost():
    index, load, pv = make_scenario()

    configuration = SurplusConfiguration(
        grid_export=GridExportCapability(
            enabled=True,
            limit_kw=5.0,
            compensation_mode=ExportCompensationMode.FIXED,
            fixed_price_per_kWh=0.08,
        )
    )

    frame = allocate_surplus(index.index, load, pv, configuration)

    energy = calculate_energy_metrics(
        frame, timestep_hours=index.timestep_hours
    )

    economics = calculate_economic_metrics(
        frame,
        energy,
        timestep_hours=index.timestep_hours,
        import_price_per_kWh=np.full(index.interval_count, 0.20),
        export_price_per_kWh=0.08,
        carbon_intensity_g_per_kWh=np.full(index.interval_count, 250.0),
        degradation_cost_per_kWh=0.03,
        carbon_weight_dollars_per_kgCO2=0.20,
        horizon_days=1.0,
    )

    # 30 kWh exported at $0.08.
    assert economics.export_revenue == pytest.approx(2.40)
    assert economics.import_energy_cost == pytest.approx(
        energy.import_energy_kWh * 0.20
    )
    assert economics.net_energy_cost == pytest.approx(
        economics.import_energy_cost - 2.40
    )
    # No battery operation, so no degradation and no cycling.
    assert economics.battery_degradation_cost == pytest.approx(0.0)
    assert economics.average_daily_equivalent_full_cycles == pytest.approx(0.0)
    assert economics.monetized_carbon_cost == pytest.approx(
        0.20 * economics.emissions_kgCO2
    )
    assert economics.carbon_adjusted_operating_cost == pytest.approx(
        economics.total_explicit_operating_cost
        + economics.monetized_carbon_cost
    )


def test_equivalent_full_cycles_is_zero_without_a_battery():
    index, load, pv = make_scenario()

    frame = allocate_surplus(
        index.index, load, pv, default_surplus_configuration()
    )

    energy = calculate_energy_metrics(
        frame, timestep_hours=index.timestep_hours
    )

    economics = calculate_economic_metrics(
        frame,
        energy,
        timestep_hours=index.timestep_hours,
        usable_battery_capacity_kWh=None,
        horizon_days=1.0,
    )

    # No division by zero: reported as zero, not NaN or an exception.
    assert economics.average_daily_equivalent_full_cycles == 0.0


def test_average_daily_efc_divides_by_horizon_days():
    index, load, pv = make_scenario(days=4)

    charge = np.full(index.interval_count, 2.0)
    discharge = np.full(index.interval_count, 2.0)

    frame = allocate_surplus(
        index.index,
        load,
        pv,
        SurplusConfiguration(
            grid_export=GridExportCapability(enabled=True, limit_kw=None)
        ),
        battery_charge_kw=charge,
        battery_discharge_kw=discharge,
    )

    energy = calculate_energy_metrics(
        frame, timestep_hours=index.timestep_hours
    )

    economics = calculate_economic_metrics(
        frame,
        energy,
        timestep_hours=index.timestep_hours,
        usable_battery_capacity_kWh=20.0,
        horizon_days=4.0,
    )

    total_cycles = energy.battery_throughput_kWh / (2 * 20.0)

    assert economics.average_daily_equivalent_full_cycles == pytest.approx(
        total_cycles / 4.0
    )
