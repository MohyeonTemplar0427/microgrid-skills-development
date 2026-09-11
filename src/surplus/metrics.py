"""Physical and economic metrics for one scenario.

Units are explicit in every name: ``_kw`` is power at an instant, ``_kWh`` is
energy over the horizon. Converting between them always goes through the
interval duration, never by assuming 15 minutes.
"""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass
class EnergyMetrics:
    """Energy accounting for one scenario, all in kWh unless named otherwise."""

    available_pv_energy_kWh: float
    actual_pv_energy_kWh: float
    self_consumed_pv_energy_kWh: float
    pv_charging_battery_energy_kWh: float
    flexible_load_energy_kWh: float
    exported_energy_kWh: float
    curtailed_pv_energy_kWh: float
    curtailment_percent: float
    import_energy_kWh: float
    native_load_energy_kWh: float
    total_load_energy_kWh: float
    peak_grid_import_kw: float
    battery_charge_energy_kWh: float
    battery_discharge_energy_kWh: float
    battery_throughput_kWh: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass
class EconomicMetrics:
    """Cost accounting for one scenario, all in dollars."""

    import_energy_cost: float
    export_revenue: float
    net_energy_cost: float
    battery_degradation_cost: float
    total_explicit_operating_cost: float
    emissions_kgCO2: float
    monetized_carbon_cost: float
    carbon_adjusted_operating_cost: float
    average_daily_equivalent_full_cycles: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def calculate_energy_metrics(
    dispatch: pd.DataFrame,
    *,
    timestep_hours: float,
) -> EnergyMetrics:
    """Energy totals from an allocated dispatch frame."""

    def total(column: str) -> float:
        if column not in dispatch.columns:
            return 0.0

        return float(
            dispatch[column].to_numpy(dtype=float).sum() * timestep_hours
        )

    available = total("pv_available_kw")
    actual = total("pv_output_kw")
    curtailed = total("pv_curtailed_kw")

    # Self-consumed PV is PV that served on-site load directly, under the
    # PV-first convention documented in allocation.py. Battery charging is
    # reported separately rather than folded in, because stored energy may
    # later be exported rather than consumed.
    self_consumed = total("pv_serving_native_load_kw") + total(
        "flexible_load_kw"
    )

    charge = total("battery_charge_kw")
    discharge = total("battery_discharge_kw")

    peak_import = (
        float(dispatch["grid_import_kw"].max())
        if "grid_import_kw" in dispatch.columns and len(dispatch)
        else 0.0
    )

    return EnergyMetrics(
        available_pv_energy_kWh=available,
        actual_pv_energy_kWh=actual,
        self_consumed_pv_energy_kWh=self_consumed,
        pv_charging_battery_energy_kWh=total("pv_charging_battery_kw"),
        flexible_load_energy_kWh=total("flexible_load_kw"),
        exported_energy_kWh=total("grid_export_kw"),
        curtailed_pv_energy_kWh=curtailed,
        curtailment_percent=(
            100.0 * curtailed / available if available > 0 else 0.0
        ),
        import_energy_kWh=total("grid_import_kw"),
        native_load_energy_kWh=total("native_load_kw"),
        total_load_energy_kWh=total("total_load_kw"),
        peak_grid_import_kw=peak_import,
        battery_charge_energy_kWh=charge,
        battery_discharge_energy_kWh=discharge,
        battery_throughput_kWh=charge + discharge,
    )


def calculate_economic_metrics(
    dispatch: pd.DataFrame,
    energy_metrics: EnergyMetrics,
    *,
    timestep_hours: float,
    import_price_per_kWh: np.ndarray | None = None,
    export_price_per_kWh: np.ndarray | float | None = None,
    carbon_intensity_g_per_kWh: np.ndarray | None = None,
    degradation_cost_per_kWh: float = 0.0,
    carbon_weight_dollars_per_kgCO2: float = 0.0,
    usable_battery_capacity_kWh: float | None = None,
    horizon_days: float = 1.0,
) -> EconomicMetrics:
    """Cost, emissions and cycling for one scenario."""

    import_kWh = (
        dispatch["grid_import_kw"].to_numpy(dtype=float) * timestep_hours
    )

    export_kWh = (
        dispatch["grid_export_kw"].to_numpy(dtype=float) * timestep_hours
        if "grid_export_kw" in dispatch.columns
        else np.zeros(len(dispatch))
    )

    import_cost = (
        float((import_kWh * np.asarray(import_price_per_kWh, dtype=float)).sum())
        if import_price_per_kWh is not None
        else 0.0
    )

    if export_price_per_kWh is None:
        export_revenue = 0.0
    elif isinstance(export_price_per_kWh, (int, float)):
        export_revenue = float(export_kWh.sum() * export_price_per_kWh)
    else:
        export_revenue = float(
            (export_kWh * np.asarray(export_price_per_kWh, dtype=float)).sum()
        )

    emissions_kgCO2 = (
        float(
            (
                import_kWh
                * np.asarray(carbon_intensity_g_per_kWh, dtype=float)
            ).sum()
            / 1000.0
        )
        if carbon_intensity_g_per_kWh is not None
        else 0.0
    )

    if (
        not np.isfinite(carbon_weight_dollars_per_kgCO2)
        or carbon_weight_dollars_per_kgCO2 < 0
    ):
        raise ValueError(
            "Carbon weight must be a nonnegative finite value in $/kgCO2."
        )

    degradation_cost = (
        energy_metrics.battery_throughput_kWh * degradation_cost_per_kWh
    )
    total_explicit_operating_cost = (
        import_cost - export_revenue + degradation_cost
    )
    monetized_carbon_cost = (
        carbon_weight_dollars_per_kgCO2 * emissions_kgCO2
    )

    # Equivalent full cycles is throughput over twice the usable capacity: one
    # full cycle is a charge and a discharge. With no battery there is no
    # usable capacity and the ratio is undefined, so it is reported as zero
    # rather than dividing by zero.
    if usable_battery_capacity_kWh and usable_battery_capacity_kWh > 0:
        equivalent_full_cycles = energy_metrics.battery_throughput_kWh / (
            2 * usable_battery_capacity_kWh
        )
    else:
        equivalent_full_cycles = 0.0

    return EconomicMetrics(
        import_energy_cost=import_cost,
        export_revenue=export_revenue,
        net_energy_cost=import_cost - export_revenue,
        battery_degradation_cost=degradation_cost,
        total_explicit_operating_cost=total_explicit_operating_cost,
        emissions_kgCO2=emissions_kgCO2,
        monetized_carbon_cost=monetized_carbon_cost,
        carbon_adjusted_operating_cost=(
            total_explicit_operating_cost + monetized_carbon_cost
        ),
        average_daily_equivalent_full_cycles=(
            equivalent_full_cycles / horizon_days
            if horizon_days > 0
            else 0.0
        ),
    )
