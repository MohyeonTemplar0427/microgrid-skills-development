import pytest

from src.dispatch.battery import (
    Battery,
    calculate_grid_power,
    simulate_timestep,
)

def test_battery_initialization():
    battery = Battery()

    assert battery.capacity_kWh == pytest.approx(50.0)
    assert battery.minimum_energy_kWh == pytest.approx(10.0)
    assert battery.maximum_energy_kWh == pytest.approx(40.0)
    assert battery.energy_kWh == pytest.approx(10.0)
    assert battery.SOC_percentage() == pytest.approx(20.0)


def test_battery_charging():
    battery = Battery()

    battery.update_energy(
        charge_kw=5.0,
        discharge_kw=0.0,
        dt_hours=0.25,
    )

    assert battery.energy_kWh == pytest.approx(11.1875)
    assert battery.SOC_percentage() == pytest.approx(22.375)


def test_battery_discharging():
    battery = Battery(energy_kWh=25.0)

    battery.update_energy(
        charge_kw=0.0,
        discharge_kw=4.0,
        dt_hours=0.25,
    )

    expected_energy = 25.0 - (4.0 / 0.95) * 0.25

    assert battery.energy_kWh == pytest.approx(expected_energy)


def test_charge_power_limit():
    battery = Battery()

    with pytest.raises(ValueError):
        battery.update_energy(
            charge_kw=21.0,
            discharge_kw=0.0,
        )

def test_discharge_power_limit():
    battery = Battery()

    with pytest.raises(ValueError):
        battery.update_energy(
            charge_kw=0.0,
            discharge_kw=21.0,
        )


def test_simultaneous_charge_and_discharge():
    battery = Battery()
    
    with pytest.raises(ValueError):
        battery.update_energy(
            charge_kw=1.0,
            discharge_kw=1.0,
        )


def test_discharge_below_minimum_energy():
    battery = Battery(energy_kWh = 10.0)

    with pytest.raises(ValueError):
        battery.update_energy(
            charge_kw=0.0,
            discharge_kw=11.0,
        )
    
    assert battery.energy_kWh == pytest.approx(10.0)


def test_charge_above_maximum_energy():
    battery = Battery(energy_kWh = 40.0)
    with pytest.raises(ValueError):
        battery.update_energy(
            charge_kw=11.0,
            discharge_kw=0.0,
        )

    assert battery.energy_kWh == pytest.approx(40.0)


def test_negative_timestep():
    battery = Battery()
    with pytest.raises(ValueError):
        battery.update_energy(
            charge_kw=1.0,
            discharge_kw=0.0,
            dt_hours=-0.1,
        )


def test_grid_import():
    grid_kw = calculate_grid_power(
        load_kw=30.0,
        pv_kw=20.0,
        charge_kw=5.0,
        discharge_kw=0.0,
    )

    assert grid_kw == pytest.approx(15.0)

def test_grid_export():
    grid_kw = calculate_grid_power(
        load_kw=10.0,
        pv_kw=20.0,
        charge_kw=0.0,
        discharge_kw=0.0,
    )

    assert grid_kw == pytest.approx(-10.0)


def test_negative_load():
    with pytest.raises(ValueError):
        calculate_grid_power(
            load_kw=-5.0,
            pv_kw=10.0,
            charge_kw=0.0,
            discharge_kw=0.0,
        )

def test_negative_pv():
    with pytest.raises(ValueError):
        calculate_grid_power(
            load_kw=10.0,
            pv_kw=-5.0,
            charge_kw=0.0,
            discharge_kw=0.0,
        )

def test_simulate_timestep_charging():
    battery = Battery()

    result = simulate_timestep(
        battery=battery,
        load_kw=30.0,
        pv_kw=20.0,
        charge_kw=5.0,
        discharge_kw=0.0,
        dt_hours=0.25,
    )

    assert result["energy_kWh"] == pytest.approx(11.1875)
    assert result["SOC_percentage"] == pytest.approx(22.375)
    assert result["grid_import"] == pytest.approx(15.0)

    assert battery.energy_kWh == pytest.approx(11.1875)


def test_simulate_timestep_export():
    battery = Battery()

    result = simulate_timestep(
        battery=battery,
        load_kw=10.0,
        pv_kw=20.0,
        charge_kw=0.0,
        discharge_kw=0.0,
        dt_hours=0.25,
    )
    assert result["grid_import"] == pytest.approx(-10.0)
    assert result["energy_kWh"] == pytest.approx(10.0)


def test_invalid_load_preserves_battery_state():
    battery = Battery(energy_kWh=25.0)

    with pytest.raises(ValueError):
        simulate_timestep(
            battery=battery,
            load_kw=-5.0,
            pv_kw=20.0,
            charge_kw=5.0,
            discharge_kw=0.0,
        )

    assert battery.energy_kWh == pytest.approx(25.0)


def test_invalid_battery_command_preserves_state():
    battery = Battery(energy_kWh=25.0)

    with pytest.raises(ValueError):
        simulate_timestep(
            battery=battery,
            load_kw=30.0,
            pv_kw=20.0,
            charge_kw=21.0,
            discharge_kw=0.0,
        )

    assert battery.energy_kWh == pytest.approx(25.0)
