"""Surplus-PV capabilities.

Export, flexible load and curtailment are **coexisting capabilities**, not
four mutually exclusive modes. A site may export up to a limit, divert some
surplus to a flexible load, and curtail whatever remains -- all in the same
interval.

Defaults are deliberately conservative and physically safe:

* grid export **disabled**
* flexible load **disabled**
* remaining surplus **curtailed**

Curtailment is always available and is the final feasibility mechanism: with
export and flexible load both off, any surplus is simply not produced, which
is always physically achievable.
"""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd


class ExportCompensationMode(StrEnum):
    """How exported energy is paid for."""

    NONE = "none"
    FIXED = "fixed"
    CSV = "csv"
    TARIFF = "tariff"


class SurplusConfigurationError(ValueError):
    pass


@dataclass
class GridExportCapability:
    """Whether and how much surplus may flow to the utility."""

    enabled: bool = False
    limit_kw: float | None = None
    compensation_mode: ExportCompensationMode = ExportCompensationMode.NONE
    fixed_price_per_kWh: float = 0.0
    price_series_per_kWh: pd.Series | None = None

    def __post_init__(self) -> None:
        self.compensation_mode = ExportCompensationMode(
            self.compensation_mode
        )

        if self.limit_kw is not None:
            if not np.isfinite(self.limit_kw) or self.limit_kw < 0:
                raise SurplusConfigurationError(
                    f"Export limit must be a nonnegative finite kW value or "
                    f"None for unlimited; received {self.limit_kw}."
                )

        if self.compensation_mode == ExportCompensationMode.FIXED:
            if (
                not np.isfinite(self.fixed_price_per_kWh)
                or self.fixed_price_per_kWh < 0
            ):
                raise SurplusConfigurationError(
                    f"Fixed export price must be nonnegative and finite; "
                    f"received {self.fixed_price_per_kWh}."
                )

        if (
            self.compensation_mode == ExportCompensationMode.CSV
            and self.price_series_per_kWh is None
        ):
            raise SurplusConfigurationError(
                "CSV export compensation requires price_series_per_kWh."
            )

        if self.compensation_mode == ExportCompensationMode.TARIFF:
            raise SurplusConfigurationError(
                "Tariff-based export compensation is not implemented. A "
                "tariff export rule (NEM, NBT or a feed-in rate) has not been "
                "modelled; use 'fixed' or 'csv' compensation, or 'none'."
            )

    @property
    def is_unlimited(self) -> bool:
        return self.enabled and self.limit_kw is None

    def limit_for_intervals(self, interval_count: int) -> np.ndarray:
        """Per-interval export ceiling in kW. Zero when disabled."""

        if not self.enabled:
            return np.zeros(interval_count)

        if self.limit_kw is None:
            return np.full(interval_count, np.inf)

        return np.full(interval_count, float(self.limit_kw))

    def price_for_intervals(self, interval_count: int) -> np.ndarray:
        """Per-interval export compensation in $/kWh."""

        if (
            not self.enabled
            or self.compensation_mode == ExportCompensationMode.NONE
        ):
            return np.zeros(interval_count)

        if self.compensation_mode == ExportCompensationMode.FIXED:
            return np.full(interval_count, float(self.fixed_price_per_kWh))

        prices = np.asarray(self.price_series_per_kWh, dtype=float)

        if len(prices) != interval_count:
            raise SurplusConfigurationError(
                f"Export price series has {len(prices)} values but the "
                f"horizon has {interval_count} intervals."
            )

        if not np.isfinite(prices).all():
            raise SurplusConfigurationError(
                "Export price series contains non-finite values."
            )

        return prices

    def describe(self) -> str:
        if not self.enabled:
            return "Export disabled"

        ceiling = (
            "unlimited"
            if self.limit_kw is None
            else f"{self.limit_kw:.2f} kW"
        )

        return (
            f"Export {ceiling}, compensation "
            f"{self.compensation_mode.value}"
        )


@dataclass
class FlexibleLoadCapability:
    """Controllable load that can absorb surplus PV.

    Capacity may be a constant kW or a per-interval series. Surplus beyond
    what it can absorb still falls through to curtailment.
    """

    enabled: bool = False
    maximum_kw: float = 0.0
    availability_series_kw: pd.Series | None = None

    def __post_init__(self) -> None:
        if self.enabled and self.availability_series_kw is None:
            if not np.isfinite(self.maximum_kw) or self.maximum_kw < 0:
                raise SurplusConfigurationError(
                    f"Flexible load maximum must be nonnegative and finite; "
                    f"received {self.maximum_kw}."
                )

    def availability_for_intervals(self, interval_count: int) -> np.ndarray:
        """Per-interval absorbable kW. Zero when disabled."""

        if not self.enabled:
            return np.zeros(interval_count)

        if self.availability_series_kw is None:
            return np.full(interval_count, float(self.maximum_kw))

        values = np.asarray(self.availability_series_kw, dtype=float)

        if len(values) != interval_count:
            raise SurplusConfigurationError(
                f"Flexible load availability has {len(values)} values but the "
                f"horizon has {interval_count} intervals."
            )

        if (values < 0).any() or not np.isfinite(values).all():
            raise SurplusConfigurationError(
                "Flexible load availability must be nonnegative and finite."
            )

        return values

    def describe(self) -> str:
        if not self.enabled:
            return "Flexible load disabled"

        if self.availability_series_kw is not None:
            return "Flexible load from time series"

        return f"Flexible load up to {self.maximum_kw:.2f} kW"


@dataclass
class SurplusConfiguration:
    """The complete surplus-PV policy for one analysis.

    Curtailment has no enable flag: it is always available, and is what
    absorbs whatever export and flexible load do not.
    """

    grid_export: GridExportCapability = None
    flexible_load: FlexibleLoadCapability = None

    def __post_init__(self) -> None:
        if self.grid_export is None:
            self.grid_export = GridExportCapability()

        if self.flexible_load is None:
            self.flexible_load = FlexibleLoadCapability()

    @property
    def curtailment_is_only_outlet(self) -> bool:
        return not self.grid_export.enabled and not self.flexible_load.enabled

    def describe(self) -> str:
        return (
            f"{self.grid_export.describe()}; "
            f"{self.flexible_load.describe()}; "
            f"surplus beyond these is curtailed"
        )


def default_surplus_configuration() -> SurplusConfiguration:
    """Export off, flexible load off, everything else curtailed."""

    return SurplusConfiguration(
        grid_export=GridExportCapability(enabled=False),
        flexible_load=FlexibleLoadCapability(enabled=False),
    )
