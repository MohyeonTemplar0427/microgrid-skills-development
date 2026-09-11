"""Versioned tariff definitions.

Rates are **data with effective dates**, not constants. A tariff that was
correct in 2026 is wrong in 2027, so every definition carries an effective
window, a source-document URL and version metadata, and lookups are made for
a specific date.

Nothing here reads a GUI widget or performs a billing calculation; this module
only describes what a tariff *is*. Charges are computed in
:mod:`src.billing.charges`.
"""

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

import pandas as pd


class ServiceVoltageClass(StrEnum):
    """Service voltage determines which rate schedule applies."""

    SECONDARY = "secondary"      # below 2,400 V
    PRIMARY = "primary"          # 2,400 V to 50 kV
    TRANSMISSION = "transmission"


class CustomerClass(StrEnum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    INDUSTRIAL = "industrial"
    AGRICULTURAL = "agricultural"


class ServiceType(StrEnum):
    """Who supplies the generation component."""

    BUNDLED = "bundled"
    CCA = "cca"
    DIRECT_ACCESS = "direct_access"


class Season(StrEnum):
    SUMMER = "summer"
    WINTER = "winter"


class DemandChargeBasis(StrEnum):
    MAXIMUM = "maximum"              # highest interval demand in the period
    PEAK_PERIOD = "peak_period"      # highest demand within TOU peak hours
    PART_PEAK_PERIOD = "part_peak_period"


class TariffError(ValueError):
    pass


@dataclass(frozen=True)
class TOUPeriod:
    """One time-of-use energy rate block.

    ``start_hour`` is inclusive and ``end_hour`` exclusive, in local
    wall-clock hours. A block may wrap past midnight. ``months`` restricts the
    block to specific calendar months (1-12); empty means all months.
    """

    name: str
    rate_per_kWh: float
    start_hour: int
    end_hour: int
    season: Season | None = None
    months: frozenset[int] = frozenset()
    priority: int = 0

    def __post_init__(self) -> None:
        if self.rate_per_kWh < 0:
            raise TariffError(
                f"TOU rate for {self.name!r} must be nonnegative."
            )

        for label, hour in (
            ("start_hour", self.start_hour),
            ("end_hour", self.end_hour),
        ):
            if not 0 <= hour <= 24:
                raise TariffError(
                    f"{self.name!r} {label} must be within 0..24; received "
                    f"{hour}."
                )

        invalid_months = set(self.months) - set(range(1, 13))

        if invalid_months:
            raise TariffError(
                f"{self.name!r} has invalid months {sorted(invalid_months)}."
            )

    @property
    def wraps_midnight(self) -> bool:
        return self.end_hour < self.start_hour

    def matches(
        self,
        hours,
        months,
        seasons,
    ):
        """Boolean mask of intervals this block covers."""

        if self.start_hour == self.end_hour:
            in_hours = hours == hours  # full day
        elif self.wraps_midnight:
            in_hours = (hours >= self.start_hour) | (hours < self.end_hour)
        else:
            in_hours = (hours >= self.start_hour) & (hours < self.end_hour)

        mask = in_hours

        if self.months:
            mask = mask & months.isin(list(self.months))

        if self.season is not None:
            mask = mask & (seasons == self.season.value)

        return mask


@dataclass(frozen=True)
class DemandChargeComponent:
    """One demand-charge line item, billed per kW of billing-period peak."""

    name: str
    rate_per_kW: float
    basis: DemandChargeBasis = DemandChargeBasis.MAXIMUM
    season: Season | None = None

    def __post_init__(self) -> None:
        if self.rate_per_kW < 0:
            raise TariffError(
                f"Demand rate for {self.name!r} must be nonnegative."
            )


@dataclass(frozen=True)
class ExportCompensationRule:
    """How exported energy is credited under this tariff."""

    name: str = "none"
    rate_per_kWh: float | None = None
    implemented: bool = False
    note: str = ""


@dataclass(frozen=True)
class SeasonDefinition:
    """Which calendar months fall in which season."""

    summer_months: frozenset[int]

    def season_for_months(self, months):
        return pd.Series(
            [
                Season.SUMMER.value
                if month in self.summer_months
                else Season.WINTER.value
                for month in months
            ],
            index=getattr(months, "index", None),
        )


@dataclass(frozen=True)
class TariffDefinition:
    """A complete, versioned tariff."""

    tariff_id: str
    name: str
    utility: str
    effective_start: date
    service_voltage_class: ServiceVoltageClass
    customer_class: CustomerClass
    service_type: ServiceType
    season_definition: SeasonDefinition
    tou_periods: tuple[TOUPeriod, ...]
    source_url: str
    version: str
    effective_end: date | None = None
    daily_customer_charge: float | None = None
    monthly_customer_charge: float | None = None
    demand_charges: tuple[DemandChargeComponent, ...] = ()
    export_rule: ExportCompensationRule = field(
        default_factory=ExportCompensationRule
    )
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.tou_periods:
            raise TariffError(
                f"Tariff {self.tariff_id!r} defines no TOU periods."
            )

        if (
            self.daily_customer_charge is None
            and self.monthly_customer_charge is None
        ):
            raise TariffError(
                f"Tariff {self.tariff_id!r} defines no customer charge."
            )

        if (
            self.effective_end is not None
            and self.effective_end < self.effective_start
        ):
            raise TariffError(
                f"Tariff {self.tariff_id!r} ends before it begins."
            )

    def is_effective_on(self, on_date: date) -> bool:
        if on_date < self.effective_start:
            return False

        return self.effective_end is None or on_date <= self.effective_end

    def season_for(self, timestamps: pd.DatetimeIndex) -> pd.Series:
        months = pd.Series(timestamps.month)
        return self.season_definition.season_for_months(months)

    def energy_rates(self, timestamps: pd.DatetimeIndex) -> pd.Series:
        """Return the $/kWh energy rate for each interval.

        Rates are matched on **local wall-clock** hour, so a 4 p.m. peak stays
        at 4 p.m. local across a daylight-saving transition.
        """

        hours = pd.Series(timestamps.hour)
        months = pd.Series(timestamps.month)
        seasons = self.season_for(timestamps)

        rates = pd.Series(float("nan"), index=range(len(timestamps)))

        # Higher priority wins where blocks overlap; a super-off-peak window
        # carved out of a broader off-peak block is expressed that way.
        for period in sorted(
            self.tou_periods,
            key=lambda p: p.priority,
            reverse=True,
        ):
            covered = period.matches(hours, months, seasons)
            rates = rates.mask(covered & rates.isna(), period.rate_per_kWh)

        if rates.isna().any():
            position = int(rates.isna().idxmax())
            raise TariffError(
                f"Tariff {self.tariff_id!r} has no rate covering "
                f"{timestamps[position]}. TOU periods must cover every hour "
                f"of every season."
            )

        return rates

    def period_names(self, timestamps: pd.DatetimeIndex) -> pd.Series:
        hours = pd.Series(timestamps.hour)
        months = pd.Series(timestamps.month)
        seasons = self.season_for(timestamps)

        names = pd.Series(None, index=range(len(timestamps)), dtype=object)

        for period in sorted(
            self.tou_periods,
            key=lambda p: p.priority,
            reverse=True,
        ):
            covered = period.matches(hours, months, seasons)
            names = names.mask(covered & names.isna(), period.name)

        return names

    def customer_charge_for(self, billing_days: float) -> float:
        """Customer charge for one meter over ``billing_days`` days."""

        if billing_days < 0:
            raise TariffError("billing_days must not be negative.")

        if self.daily_customer_charge is not None:
            return self.daily_customer_charge * billing_days

        # A monthly charge is prorated on a 30-day month.
        return self.monthly_customer_charge * (billing_days / 30.0)


TARIFF_REGISTRY: dict[str, TariffDefinition] = {}


def register_tariff(tariff: TariffDefinition) -> TariffDefinition:
    TARIFF_REGISTRY[tariff.tariff_id] = tariff
    return tariff


def get_tariff(
    tariff_id: str,
    on_date: date | None = None,
) -> TariffDefinition:
    """Look up a tariff, optionally checking it is effective on a date."""

    if tariff_id not in TARIFF_REGISTRY:
        raise TariffError(
            f"Unknown tariff {tariff_id!r}. Known tariffs: "
            f"{sorted(TARIFF_REGISTRY)}."
        )

    tariff = TARIFF_REGISTRY[tariff_id]

    if on_date is not None and not tariff.is_effective_on(on_date):
        raise TariffError(
            f"Tariff {tariff_id!r} version {tariff.version} is effective from "
            f"{tariff.effective_start}"
            + (
                f" to {tariff.effective_end}"
                if tariff.effective_end
                else ""
            )
            + f", which does not cover {on_date}. Rates change over time; "
            f"add the applicable version rather than reusing this one."
        )

    return tariff


def supported_tariffs() -> list[str]:
    return sorted(TARIFF_REGISTRY)
