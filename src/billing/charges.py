"""Billing calculation.

Pure functions over an interval table plus a tariff and a meter topology.

**Demand charges are not summed across intervals.** A demand charge bills the
single highest 15-minute average import in each billing period, once. Summing
per-interval demand would overstate cost by roughly the number of intervals,
which is the most common way this calculation goes wrong.

Billing periods are calendar months. A horizon spanning several months gets a
separate peak, and a separate customer charge, for each.
"""

from dataclasses import dataclass, field
from collections.abc import Mapping

import numpy as np
import pandas as pd

from .meter_topology import MeterTopology, MeterTopologyMode
from .tariffs import DemandChargeBasis, TariffDefinition, TariffError


class BillingError(ValueError):
    pass


@dataclass
class BillingPeriodResult:
    """Charges for one meter over one billing period."""

    meter_id: str
    tariff_id: str
    period_label: str
    billing_days: float
    customer_charge: float
    import_energy_kWh: float
    import_energy_charge: float
    billed_peak_kw: float
    simulated_peak_kw: float
    demand_charge: float
    export_energy_kWh: float
    export_credit: float
    is_partial_period: bool = False
    previous_peak_was_known: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_utility_charge(self) -> float:
        return (
            self.customer_charge
            + self.import_energy_charge
            + self.demand_charge
            - self.export_credit
        )


@dataclass
class BillingResult:
    """All billing periods and meters for one scenario."""

    periods: tuple[BillingPeriodResult, ...]
    battery_degradation_cost: float = 0.0
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def customer_charge(self) -> float:
        return sum(period.customer_charge for period in self.periods)

    @property
    def import_energy_charge(self) -> float:
        return sum(period.import_energy_charge for period in self.periods)

    @property
    def demand_charge(self) -> float:
        return sum(period.demand_charge for period in self.periods)

    @property
    def export_credit(self) -> float:
        return sum(period.export_credit for period in self.periods)

    @property
    def import_energy_kWh(self) -> float:
        return sum(period.import_energy_kWh for period in self.periods)

    @property
    def export_energy_kWh(self) -> float:
        return sum(period.export_energy_kWh for period in self.periods)

    @property
    def total_utility_charge(self) -> float:
        return sum(period.total_utility_charge for period in self.periods)

    @property
    def total_explicit_operating_cost(self) -> float:
        """Utility charges plus battery degradation.

        Degradation is a real operating cost but is not a utility charge, so
        it is reported separately and only combined here.
        """

        return self.total_utility_charge + self.battery_degradation_cost

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "meter_id": period.meter_id,
                    "tariff_id": period.tariff_id,
                    "period": period.period_label,
                    "billing_days": period.billing_days,
                    "customer_charge": period.customer_charge,
                    "import_energy_kWh": period.import_energy_kWh,
                    "import_energy_charge": period.import_energy_charge,
                    "billed_peak_kw": period.billed_peak_kw,
                    "demand_charge": period.demand_charge,
                    "export_energy_kWh": period.export_energy_kWh,
                    "export_credit": period.export_credit,
                    "total_utility_charge": period.total_utility_charge,
                    "is_partial_period": period.is_partial_period,
                }
                for period in self.periods
            ]
        )


def assign_billing_periods(timestamps: pd.DatetimeIndex) -> pd.Series:
    """Label each interval with its calendar-month billing period."""

    return pd.Series(
        [f"{ts.year:04d}-{ts.month:02d}" for ts in timestamps],
        index=range(len(timestamps)),
    )


def calculate_demand_peak(
    import_kw: np.ndarray,
    *,
    previous_peak_kw: float | Mapping[str, float] | None = None,
) -> tuple[float, float, bool]:
    """Return (billed_peak, simulated_peak, previous_peak_was_known).

    For a partial billing cycle the utility bills against the peak already
    established earlier in the period, so:

        billed_peak = max(previous_peak, simulated_peak)

    When the previous peak is unknown, the simulated peak is used and the
    result is flagged, because the real bill can only be higher.
    """

    simulated_peak = float(np.max(import_kw)) if len(import_kw) else 0.0

    if previous_peak_kw is None:
        return simulated_peak, simulated_peak, False

    if previous_peak_kw < 0:
        raise BillingError("previous_peak_kw must not be negative.")

    return (
        max(float(previous_peak_kw), simulated_peak),
        simulated_peak,
        True,
    )


def calculate_meter_billing(
    dispatch: pd.DataFrame,
    tariff: TariffDefinition,
    *,
    meter_id: str,
    timestep_hours: float,
    import_column: str = "grid_import_kw",
    export_column: str = "grid_export_kw",
    export_price_per_kWh: np.ndarray | float | None = None,
    previous_peak_kw: float | None = None,
    utility_account_count: int = 1,
    expect_full_periods: bool = True,
) -> tuple[BillingPeriodResult, ...]:
    """Bill one meter across every calendar-month period in the horizon."""

    if "timestamp" not in dispatch.columns:
        raise BillingError("Dispatch data is missing a timestamp column.")

    timestamps = pd.DatetimeIndex(dispatch["timestamp"])

    if timestamps.tz is None:
        raise BillingError(
            "Billing requires timezone-aware timestamps: TOU periods and "
            "billing months are defined in local time."
        )

    rates = tariff.energy_rates(timestamps).to_numpy(dtype=float)
    import_kw = dispatch[import_column].to_numpy(dtype=float)

    export_kw = (
        dispatch[export_column].to_numpy(dtype=float)
        if export_column in dispatch.columns
        else np.zeros(len(dispatch))
    )

    export_rates = _export_rate_array(export_price_per_kWh, len(dispatch))

    periods = assign_billing_periods(timestamps)

    invalid_dates = sorted(
        {
            timestamp.date()
            for timestamp in timestamps
            if not tariff.is_effective_on(timestamp.date())
        }
    )

    if invalid_dates:
        raise TariffError(
            f"Tariff {tariff.tariff_id!r} version {tariff.version} is not "
            f"effective on {invalid_dates[0]}. Its effective window begins "
            f"{tariff.effective_start}"
            + (
                f" and ends {tariff.effective_end}"
                if tariff.effective_end is not None
                else ""
            )
            + ". Select the tariff version covering the analysis date."
        )

    unsupported_demand_components = [
        component.name
        for component in tariff.demand_charges
        if component.basis != DemandChargeBasis.MAXIMUM
    ]

    if unsupported_demand_components:
        raise BillingError(
            "Demand-charge bases other than maximum demand are not yet "
            "implemented. Unsupported components: "
            f"{unsupported_demand_components}."
        )

    results = []

    for period_index, label in enumerate(periods.unique()):
        mask = (periods == label).to_numpy()

        period_import_kw = import_kw[mask]
        period_export_kw = export_kw[mask]
        period_rates = rates[mask]
        period_export_rates = export_rates[mask]

        import_kWh = period_import_kw * timestep_hours
        export_kWh = period_export_kw * timestep_hours

        if isinstance(previous_peak_kw, Mapping):
            prior_peak_for_period = previous_peak_kw.get(label)
        elif period_index == 0:
            prior_peak_for_period = previous_peak_kw
        else:
            prior_peak_for_period = None

        billed_peak, simulated_peak, previous_known = calculate_demand_peak(
            period_import_kw,
            previous_peak_kw=prior_peak_for_period,
        )

        demand_charge = sum(
            component.rate_per_kW * billed_peak
            for component in tariff.demand_charges
            if component.basis == DemandChargeBasis.MAXIMUM
        )

        period_timestamps = timestamps[mask]
        billing_days = float(
            len(period_timestamps.normalize().unique())
        )

        is_partial = expect_full_periods and not _is_full_month(
            label,
            period_timestamps,
            timestep_hours,
        )

        warnings = []

        if is_partial and not previous_known:
            warnings.append(
                f"PARTIAL BILLING PERIOD: {label} is only "
                f"{billing_days:.2f} days and no previously established "
                f"billing peak was supplied. The demand charge reflects only "
                f"the simulated window; an actual bill can only be higher."
            )

        results.append(
            BillingPeriodResult(
                meter_id=meter_id,
                tariff_id=tariff.tariff_id,
                period_label=label,
                billing_days=billing_days,
                customer_charge=(
                    tariff.customer_charge_for(billing_days)
                    * utility_account_count
                ),
                import_energy_kWh=float(import_kWh.sum()),
                import_energy_charge=float((import_kWh * period_rates).sum()),
                billed_peak_kw=billed_peak,
                simulated_peak_kw=simulated_peak,
                demand_charge=float(demand_charge),
                export_energy_kWh=float(export_kWh.sum()),
                export_credit=float(
                    (export_kWh * period_export_rates).sum()
                ),
                is_partial_period=is_partial,
                previous_peak_was_known=previous_known,
                warnings=tuple(warnings),
            )
        )

    return tuple(results)


def calculate_billing(
    dispatch: pd.DataFrame,
    topology: MeterTopology,
    tariffs: dict[str, TariffDefinition],
    *,
    timestep_hours: float,
    export_price_per_kWh: np.ndarray | float | None = None,
    previous_peak_kw: float | None = None,
    battery_degradation_cost: float = 0.0,
    meter_dispatches: Mapping[str, pd.DataFrame] | None = None,
) -> BillingResult:
    """Bill a dispatch schedule under a meter topology.

    Single-PCC and master-meter topologies bill one aggregate account, with
    demand measured on the combined flow. Individually metered topologies bill
    each account separately, so each has its own peak and its own customer
    charge.
    """

    warnings = list(topology.approximation_warnings)

    if topology.demand_is_aggregate:
        account = topology.utility_accounts[0]
        tariff = _lookup(tariffs, topology.tariff_for(account))

        periods = calculate_meter_billing(
            dispatch,
            tariff,
            meter_id=account.meter_id,
            timestep_hours=timestep_hours,
            export_price_per_kWh=export_price_per_kWh,
            previous_peak_kw=previous_peak_kw,
            utility_account_count=1,
        )

        if topology.mode == MeterTopologyMode.MASTER_WITH_SUBMETERS:
            warnings.append(
                f"Submeters ({len(topology.submeters)}) allocate the master "
                f"bill internally and incur no separate utility customer or "
                f"demand charges."
            )

        return BillingResult(
            periods=periods,
            battery_degradation_cost=battery_degradation_cost,
            warnings=tuple(warnings),
        )

    if topology.mode == MeterTopologyMode.INDIVIDUAL_WITH_SHARED_GENERATION:
        raise BillingError(
            "Shared-generation billing is not implemented yet. Allocation "
            "percentages describe how credits are assigned, but the applicable "
            "NEM/NBT credit rules are not configured. Refusing to split the "
            "aggregate PCC flow equally because that would fabricate per-meter "
            "bills."
        )

    accounts = topology.utility_accounts

    if meter_dispatches is None and not (
        topology.uses_equal_allocation_approximation
    ):
        raise BillingError(
            "Individually metered billing requires meter_dispatches with one "
            "dispatch table per utility account. To use an equal split of the "
            "aggregate site flow instead, explicitly set "
            "uses_equal_allocation_approximation=True on the topology."
        )

    if meter_dispatches is not None:
        required_meter_ids = {account.meter_id for account in accounts}
        missing_meter_ids = required_meter_ids - set(meter_dispatches)

        if missing_meter_ids:
            raise BillingError(
                "Per-meter dispatch data is missing utility accounts: "
                f"{sorted(missing_meter_ids)}."
            )

    share = 1.0 / len(accounts)

    all_periods: list[BillingPeriodResult] = []

    for account in accounts:
        tariff = _lookup(tariffs, topology.tariff_for(account))

        if meter_dispatches is not None:
            meter_dispatch = meter_dispatches[account.meter_id]
            meter_previous_peak = previous_peak_kw
        else:
            # This approximation is used only after explicit opt-in above.
            meter_dispatch = dispatch.copy()
            meter_dispatch["grid_import_kw"] = (
                dispatch["grid_import_kw"] * share
            )

            if "grid_export_kw" in dispatch.columns:
                meter_dispatch["grid_export_kw"] = (
                    dispatch["grid_export_kw"] * share
                )

            meter_previous_peak = (
                previous_peak_kw * share
                if previous_peak_kw is not None
                else None
            )

        all_periods.extend(
            calculate_meter_billing(
                meter_dispatch,
                tariff,
                meter_id=account.meter_id,
                timestep_hours=timestep_hours,
                export_price_per_kWh=export_price_per_kWh,
                previous_peak_kw=meter_previous_peak,
                utility_account_count=1,
            )
        )

    warnings.append(
        f"Each of the {len(accounts)} utility accounts is billed "
        f"independently: separate customer charges and separate demand peaks."
    )

    return BillingResult(
        periods=tuple(all_periods),
        battery_degradation_cost=battery_degradation_cost,
        warnings=tuple(warnings),
    )


def allocate_shared_generation(
    generation_kWh: float,
    topology: MeterTopology,
) -> dict[str, float]:
    """Split shared generation across meters by allocation percentage.

    This is a billing credit. It does not claim particular electrons reached a
    particular unit.
    """

    allocations = {
        meter.meter_id: meter.allocation_percent
        for meter in topology.meters
        if meter.allocation_percent is not None
    }

    if not allocations:
        raise BillingError(
            "Topology defines no allocation percentages."
        )

    total = sum(allocations.values())

    if abs(total - 100.0) > 1e-6:
        raise BillingError(
            f"Allocation percentages sum to {total}, not 100."
        )

    return {
        meter_id: generation_kWh * percent / 100.0
        for meter_id, percent in allocations.items()
    }


def _lookup(
    tariffs: dict[str, TariffDefinition],
    tariff_id: str,
) -> TariffDefinition:
    if tariff_id not in tariffs:
        raise BillingError(
            f"Tariff {tariff_id!r} was not supplied. Available: "
            f"{sorted(tariffs)}."
        )

    return tariffs[tariff_id]


def _export_rate_array(
    export_price_per_kWh,
    interval_count: int,
) -> np.ndarray:
    if export_price_per_kWh is None:
        return np.zeros(interval_count)

    if isinstance(export_price_per_kWh, (int, float)):
        return np.full(interval_count, float(export_price_per_kWh))

    rates = np.asarray(export_price_per_kWh, dtype=float)

    if len(rates) != interval_count:
        raise BillingError(
            f"Export price series has {len(rates)} values but the horizon has "
            f"{interval_count} intervals."
        )

    return rates


def _is_full_month(
    label: str,
    timestamps: pd.DatetimeIndex,
    timestep_hours: float,
) -> bool:
    year, month = (int(part) for part in label.split("-"))
    timezone = timestamps.tz
    month_start = pd.Timestamp(year=year, month=month, day=1, tz=timezone)
    next_month_start = month_start + pd.offsets.MonthBegin(1)
    expected = pd.date_range(
        start=month_start,
        end=next_month_start,
        freq=pd.Timedelta(hours=timestep_hours),
        inclusive="left",
    )

    return timestamps.equals(expected)
