"""Price sources.

A wholesale market node is **not** a customer retail tariff. A node price is
the marginal energy price at a point on the transmission system; a retail
tariff is what a site actually pays, including delivery charges and a utility's
rate design. Modelling one as the other misstates the value of dispatch, so
they are separate source types here.

All four sources produce the same frame -- ``timestamp`` and
``price_per_kWh`` in **$/kWh** -- over an :class:`AnalysisHorizon`.

Provider-specific API behaviour stays inside the adapters in
:mod:`src.signal_pipeline.providers`; nothing in this module talks to an API
directly except by delegating to the provider registry.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .gridstatus_data import fetch_energy_prices
from .horizon import AnalysisHorizon, align_to_horizon
from .providers.base import SignalProviderError

WHOLESALE_MARKET = "wholesale_market"
FIXED_RETAIL = "fixed_retail"
TIME_OF_USE = "time_of_use"
CSV = "csv"

PRICE_MODES = (WHOLESALE_MARKET, FIXED_RETAIL, TIME_OF_USE, CSV)

# Monday is 0, matching pandas' dayofweek.
WEEKDAYS = frozenset({0, 1, 2, 3, 4})
WEEKEND = frozenset({5, 6})
ALL_DAYS = frozenset(range(7))


class PriceSourceError(SignalProviderError):
    pass


class UnsupportedPriceModeError(PriceSourceError):
    pass


class PriceScheduleError(PriceSourceError):
    pass


class PriceSource(ABC):
    """Produces one $/kWh value for every interval in a horizon."""

    mode: str

    @abstractmethod
    def build_prices(self, horizon: AnalysisHorizon) -> pd.DataFrame:
        """Return ``timestamp`` / ``price_per_kWh`` over the whole horizon."""


def _validate_price_value(value: float, label: str) -> float:
    try:
        price = float(value)
    except (TypeError, ValueError) as error:
        raise PriceSourceError(
            f"{label} must be a number; received {value!r}."
        ) from error

    if not np.isfinite(price):
        raise PriceSourceError(f"{label} must be finite; received {price}.")

    if price < 0:
        raise PriceSourceError(
            f"{label} must not be negative; received {price}."
        )

    return price


@dataclass
class WholesaleMarketPrice(PriceSource):
    """Prices from an ISO node, normalized from the ISO's $/MWh to $/kWh."""

    market_provider: str
    market_location: str
    provider_options: dict | None = None

    mode = WHOLESALE_MARKET

    def build_prices(self, horizon: AnalysisHorizon) -> pd.DataFrame:
        prices = fetch_energy_prices(
            horizon.start,
            horizon.end,
            self.market_location,
            provider=self.market_provider,
            **(self.provider_options or {}),
        )

        return align_to_horizon(
            prices[["timestamp", "price_per_kWh"]],
            horizon,
            label="Wholesale price",
        )


@dataclass
class FixedRetailPrice(PriceSource):
    """One flat $/kWh rate applied to every interval."""

    price_per_kWh: float

    mode = FIXED_RETAIL

    def __post_init__(self) -> None:
        self.price_per_kWh = _validate_price_value(
            self.price_per_kWh,
            "Fixed retail price",
        )

    def build_prices(self, horizon: AnalysisHorizon) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": horizon.index,
                "price_per_kWh": self.price_per_kWh,
            }
        )


@dataclass(frozen=True)
class TimeOfUsePeriod:
    """One priced block of local wall-clock time.

    ``start_hour`` is inclusive and ``end_hour`` exclusive, both in local
    hours. A period may wrap past midnight (``start_hour=22, end_hour=6``).
    ``days`` holds pandas weekday numbers, Monday 0 through Sunday 6.
    """

    name: str
    price_per_kWh: float
    start_hour: int
    end_hour: int
    days: frozenset[int] = ALL_DAYS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "price_per_kWh",
            _validate_price_value(
                self.price_per_kWh,
                f"Time-of-use price for period {self.name!r}",
            ),
        )

        for label, hour in (
            ("start_hour", self.start_hour),
            ("end_hour", self.end_hour),
        ):
            if not isinstance(hour, int) or not 0 <= hour <= 24:
                raise PriceScheduleError(
                    f"Period {self.name!r}: {label} must be an integer "
                    f"between 0 and 24; received {hour!r}."
                )

        if self.start_hour == self.end_hour:
            raise PriceScheduleError(
                f"Period {self.name!r} is empty: start_hour equals end_hour."
            )

        if not self.days:
            raise PriceScheduleError(
                f"Period {self.name!r} applies to no days of the week."
            )

        invalid_days = set(self.days) - ALL_DAYS

        if invalid_days:
            raise PriceScheduleError(
                f"Period {self.name!r} has invalid weekday numbers: "
                f"{sorted(invalid_days)}. Monday is 0, Sunday is 6."
            )

    @property
    def wraps_midnight(self) -> bool:
        return self.end_hour < self.start_hour

    def matches(
        self,
        hours: pd.Series,
        weekdays: pd.Series,
    ) -> pd.Series:
        """Boolean mask of the intervals this period covers."""

        if self.wraps_midnight:
            in_hours = (hours >= self.start_hour) | (hours < self.end_hour)
        else:
            in_hours = (hours >= self.start_hour) & (hours < self.end_hour)

        return in_hours & weekdays.isin(list(self.days))


@dataclass
class TimeOfUseSchedule(PriceSource):
    """A validated, reusable time-of-use tariff.

    **Daylight saving** is handled by evaluating the *local* wall-clock hour
    of each timezone-aware timestamp, so a 4pm peak stays at 4pm local on
    both sides of a transition. A spring-forward day simply has fewer
    intervals in the skipped hour, and a fall-back day has more in the
    repeated one.

    **Weekends** are expressed through each period's ``days`` set.

    **Holidays are not implemented.** A public holiday is priced with its
    normal weekday rate. Real utility tariffs usually bill holidays at
    off-peak rates, so results for a horizon containing one will overstate
    cost. Adding this needs a holiday calendar per utility, not per ISO.
    """

    periods: tuple[TimeOfUsePeriod, ...]
    default_price_per_kWh: float | None = None

    mode = TIME_OF_USE

    def __post_init__(self) -> None:
        self.periods = tuple(self.periods)

        if not self.periods:
            raise PriceScheduleError(
                "A time-of-use schedule needs at least one period."
            )

        names = [period.name for period in self.periods]

        if len(set(names)) != len(names):
            raise PriceScheduleError(
                f"Time-of-use period names must be unique; received {names}."
            )

        if self.default_price_per_kWh is not None:
            self.default_price_per_kWh = _validate_price_value(
                self.default_price_per_kWh,
                "Time-of-use default price",
            )

    def build_prices(self, horizon: AnalysisHorizon) -> pd.DataFrame:
        timestamps = pd.Series(horizon.index, name="timestamp")

        # Local wall-clock hour and weekday, which is what a tariff is
        # written against.
        hours = timestamps.dt.hour
        weekdays = timestamps.dt.dayofweek

        prices = pd.Series(np.nan, index=timestamps.index)

        for period in self.periods:
            covered = period.matches(hours, weekdays)
            prices = prices.mask(covered & prices.isna(), period.price_per_kWh)

        uncovered = prices.isna()

        if uncovered.any():
            if self.default_price_per_kWh is None:
                first_gap = timestamps[uncovered].iloc[0]
                raise PriceScheduleError(
                    f"Time-of-use schedule does not cover {int(uncovered.sum())} "
                    f"intervals, starting at {first_gap}. Add a period or set "
                    f"default_price_per_kWh."
                )

            prices = prices.fillna(self.default_price_per_kWh)

        return pd.DataFrame(
            {
                "timestamp": horizon.index,
                "price_per_kWh": prices.to_numpy(),
            }
        )


@dataclass
class CSVPrice(PriceSource):
    """Prices read from a user-supplied table.

    ``source_unit`` states what the column holds. ``$/MWh`` is divided by
    1000; ``$/kWh`` is taken as-is. Nothing is guessed from magnitude.
    """

    data: pd.DataFrame
    price_column: str = "price_per_kWh"
    source_unit: str = "$/kWh"

    mode = CSV

    SUPPORTED_UNITS = {
        "$/kWh": 1.0,
        "$/MWh": 1 / 1000,
    }

    def build_prices(self, horizon: AnalysisHorizon) -> pd.DataFrame:
        if self.source_unit not in self.SUPPORTED_UNITS:
            raise PriceSourceError(
                f"Unsupported price unit {self.source_unit!r}. "
                f"Supported units: {sorted(self.SUPPORTED_UNITS)}."
            )

        missing = {"timestamp", self.price_column} - set(self.data.columns)

        if missing:
            raise PriceSourceError(
                f"Price CSV is missing columns: {sorted(missing)}. "
                f"Received: {sorted(self.data.columns)}."
            )

        prices = self.data[["timestamp", self.price_column]].copy()

        try:
            values = pd.to_numeric(prices[self.price_column], errors="raise")
        except (TypeError, ValueError) as error:
            raise PriceSourceError(
                f"Price column {self.price_column!r} contains nonnumeric "
                f"values."
            ) from error

        if not np.isfinite(values.to_numpy(dtype=float)).all():
            raise PriceSourceError(
                f"Price column {self.price_column!r} contains non-finite "
                f"values."
            )

        if (values < 0).any():
            raise PriceSourceError(
                f"Price column {self.price_column!r} contains negative "
                f"values. Wholesale prices can legitimately be negative; if "
                f"this is a wholesale series, use the wholesale_market "
                f"source instead of csv."
            )

        prices["price_per_kWh"] = (
            values * self.SUPPORTED_UNITS[self.source_unit]
        )

        return align_to_horizon(
            prices[["timestamp", "price_per_kWh"]],
            horizon,
            label="CSV price",
        )


def build_price_source(mode: str, **options) -> PriceSource:
    """Construct a price source by mode name."""

    key = str(mode).strip().lower()

    builders = {
        WHOLESALE_MARKET: WholesaleMarketPrice,
        FIXED_RETAIL: FixedRetailPrice,
        TIME_OF_USE: TimeOfUseSchedule,
        CSV: CSVPrice,
    }

    if key not in builders:
        raise UnsupportedPriceModeError(
            f"Unknown price mode {mode!r}. Supported modes: "
            f"{list(PRICE_MODES)}."
        )

    return builders[key](**options)
