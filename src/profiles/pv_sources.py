"""PV-profile sources.

Every source produces ``pv_available_kw`` -- the maximum PV power available
from sunlight **before** curtailment. What the system actually delivers is
``pv_output_kw``, decided by the surplus allocation layer, and the difference
is ``pv_curtailed_kw``.

Keeping those distinct is the reason this module exists: the legacy ``pv_kw``
column conflated them, which made curtailment impossible to express.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from ..timeseries.interval_table import IntervalIndex, align_to_index
from ..timeseries.schema import MissingDataPolicy, PowerUnit, convert_to_kw
from .load_sources import _prepare_csv_frame


class PVSourceMode(StrEnum):
    SYNTHETIC = "synthetic"
    CSV_POWER = "csv_power"
    CSV_CAPACITY_FACTOR = "csv_capacity_factor"
    WEATHER = "weather"
    MEASURED_INVERTER = "measured_inverter"


class PVSourceError(ValueError):
    pass


class PVProfileSource(ABC):
    """Produces ``pv_available_kw`` over an interval index."""

    mode: PVSourceMode
    is_synthetic: bool = False

    @abstractmethod
    def build_pv_available_kw(
        self,
        interval_index: IntervalIndex,
    ) -> pd.Series:
        """Return one available-kW value per interval."""

    def describe(self) -> str:
        return self.mode.value


@dataclass
class SyntheticPV(PVProfileSource):
    """A smooth clear-sky demonstration curve.

    A half-sine between sunrise and sunset, scaled to the rated capacity. It
    models no weather, no shading and no seasonal declination -- it exists to
    demonstrate dispatch behaviour, not to estimate yield.
    """

    rated_pv_capacity_kw: float
    sunrise_hour: float = 6.0
    sunset_hour: float = 19.0
    peak_fraction_of_rating: float = 0.85

    mode = PVSourceMode.SYNTHETIC
    is_synthetic = True

    def __post_init__(self) -> None:
        if self.rated_pv_capacity_kw <= 0:
            raise PVSourceError(
                f"Rated PV capacity must be positive; received "
                f"{self.rated_pv_capacity_kw}."
            )

        if not 0 <= self.sunrise_hour < self.sunset_hour <= 24:
            raise PVSourceError(
                f"Sunrise ({self.sunrise_hour}) must be before sunset "
                f"({self.sunset_hour}), both within 0..24."
            )

        if not 0 < self.peak_fraction_of_rating <= 1:
            raise PVSourceError(
                "peak_fraction_of_rating must be between 0 and 1."
            )

    def build_pv_available_kw(
        self,
        interval_index: IntervalIndex,
    ) -> pd.Series:
        timestamps = interval_index.index

        hours = (
            timestamps.hour.to_numpy()
            + timestamps.minute.to_numpy() / 60.0
        )

        daylight_span = self.sunset_hour - self.sunrise_hour
        position = (hours - self.sunrise_hour) / daylight_span

        shape = np.where(
            (position >= 0) & (position <= 1),
            np.sin(np.pi * np.clip(position, 0, 1)),
            0.0,
        )

        values = (
            shape
            * self.rated_pv_capacity_kw
            * self.peak_fraction_of_rating
        )

        return pd.Series(values, name="pv_available_kw")

    def describe(self) -> str:
        return (
            f"Synthetic clear-sky, {self.rated_pv_capacity_kw:.2f} kW rated "
            f"- SYNTHETIC DATA"
        )


@dataclass
class CSVPowerPV(PVProfileSource):
    """Available PV power read directly from a table, in W, kW or MW."""

    data: pd.DataFrame
    timestamp_column: str = "timestamp"
    pv_column: str = "pv_kw"
    unit: PowerUnit | str = PowerUnit.KW
    rated_pv_capacity_kw: float | None = None
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT
    filled_interval_count: int = field(default=0, init=False)

    mode = PVSourceMode.CSV_POWER

    def build_pv_available_kw(
        self,
        interval_index: IntervalIndex,
    ) -> pd.Series:
        frame = _prepare_csv_frame(
            self.data,
            self.timestamp_column,
            self.pv_column,
            label="PV CSV",
        )

        frame["value_kw"] = convert_to_kw(frame["value"], self.unit)

        aligned, filled = align_to_index(
            frame[["timestamp", "value_kw"]],
            interval_index,
            label="PV CSV",
            missing_data_policy=self.missing_data_policy,
        )

        self.filled_interval_count = filled

        values = aligned["value_kw"].to_numpy(dtype=float)

        if (values < 0).any():
            raise PVSourceError(
                "PV CSV contains negative values. Available PV is the power "
                "sunlight makes possible and cannot be negative."
            )

        return pd.Series(values, name="pv_available_kw")

    def describe(self) -> str:
        return f"CSV available power, column {self.pv_column!r} ({self.unit})"


@dataclass
class CSVCapacityFactorPV(PVProfileSource):
    """Capacity factors scaled by the rated capacity.

        pv_available_kw = capacity_factor * rated_pv_capacity_kw

    Factors are normally in 0..1. Values above 1 are rejected by default
    because they almost always mean the column actually holds kW.
    """

    data: pd.DataFrame
    rated_pv_capacity_kw: float
    timestamp_column: str = "timestamp"
    capacity_factor_column: str = "capacity_factor"
    maximum_capacity_factor: float = 1.0
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT
    filled_interval_count: int = field(default=0, init=False)

    mode = PVSourceMode.CSV_CAPACITY_FACTOR

    def __post_init__(self) -> None:
        if self.rated_pv_capacity_kw <= 0:
            raise PVSourceError(
                f"Rated PV capacity must be positive; received "
                f"{self.rated_pv_capacity_kw}."
            )

    def build_pv_available_kw(
        self,
        interval_index: IntervalIndex,
    ) -> pd.Series:
        frame = _prepare_csv_frame(
            self.data,
            self.timestamp_column,
            self.capacity_factor_column,
            label="PV capacity-factor CSV",
        )

        aligned, filled = align_to_index(
            frame[["timestamp", "value"]],
            interval_index,
            label="PV capacity-factor CSV",
            missing_data_policy=self.missing_data_policy,
        )

        self.filled_interval_count = filled

        factors = aligned["value"].to_numpy(dtype=float)

        if (factors < 0).any():
            raise PVSourceError(
                "Capacity factors must not be negative."
            )

        if (factors > self.maximum_capacity_factor).any():
            peak = float(factors.max())
            raise PVSourceError(
                f"Capacity factor peaks at {peak:.3f}, above the maximum "
                f"{self.maximum_capacity_factor:.3f}. A capacity factor is a "
                f"fraction of rated capacity; if this column holds kW, use "
                f"the CSV available-power source instead."
            )

        return pd.Series(
            factors * self.rated_pv_capacity_kw,
            name="pv_available_kw",
        )

    def describe(self) -> str:
        return (
            f"CSV capacity factor x {self.rated_pv_capacity_kw:.2f} kW rated"
        )


@dataclass
class WeatherDerivedPVConfiguration:
    """Configuration for a future weather-to-PV model.

    **Azimuth convention:** 0 degrees north, 90 east, 180 south, 270 west.

    These fields are validated now so the GUI can collect and persist them,
    but no irradiance model consumes them yet.
    """

    latitude: float
    longitude: float
    rated_pv_capacity_kw: float
    tilt_degrees: float = 20.0
    azimuth_degrees: float = 180.0
    inverter_efficiency: float = 0.96
    system_losses_fraction: float = 0.14

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise PVSourceError(
                f"Latitude must be between -90 and 90; received "
                f"{self.latitude}."
            )

        if not -180 <= self.longitude <= 180:
            raise PVSourceError(
                f"Longitude must be between -180 and 180; received "
                f"{self.longitude}."
            )

        if self.rated_pv_capacity_kw <= 0:
            raise PVSourceError("Rated PV capacity must be positive.")

        if not 0 <= self.tilt_degrees <= 90:
            raise PVSourceError(
                f"Tilt must be between 0 (horizontal) and 90 (vertical); "
                f"received {self.tilt_degrees}."
            )

        if not 0 <= self.azimuth_degrees < 360:
            raise PVSourceError(
                f"Azimuth must be in [0, 360): 0 north, 90 east, 180 south, "
                f"270 west. Received {self.azimuth_degrees}."
            )

        if not 0 < self.inverter_efficiency <= 1:
            raise PVSourceError(
                "Inverter efficiency must be between 0 and 1."
            )

        if not 0 <= self.system_losses_fraction < 1:
            raise PVSourceError(
                "System losses must be a fraction in [0, 1)."
            )


class WeatherDerivedPV(PVProfileSource):
    """Extension point for weather-derived PV.

    **Not implemented.** No irradiance provider is wired up. Configuration is
    validated so the GUI can collect it, but building a profile raises rather
    than inventing a clear-sky curve dressed up as a weather model.
    """

    mode = PVSourceMode.WEATHER

    def __init__(self, configuration: WeatherDerivedPVConfiguration) -> None:
        self.configuration = configuration

    def build_pv_available_kw(
        self,
        interval_index: IntervalIndex,
    ) -> pd.Series:
        raise NotImplementedError(
            "Weather-derived PV is not implemented: no irradiance provider "
            "(PVGIS, NSRDB, PVWatts or similar) is connected. Use the "
            "synthetic profile for a demonstration shape, or a CSV profile "
            "for real data."
        )

    def describe(self) -> str:
        return (
            f"Weather-derived at ({self.configuration.latitude:.4f}, "
            f"{self.configuration.longitude:.4f}), tilt "
            f"{self.configuration.tilt_degrees:.0f}deg, azimuth "
            f"{self.configuration.azimuth_degrees:.0f}deg (not implemented)"
        )


class MeasuredInverterPV(PVProfileSource):
    """Extension point for live inverter telemetry.

    **Not implemented.** Measured inverter output is delivered power, which is
    already post-curtailment; deriving *available* PV from it needs either a
    curtailment signal from the inverter or a clear-sky reference model. That
    modelling decision is unresolved, so this raises instead of guessing.
    """

    mode = PVSourceMode.MEASURED_INVERTER

    SUPPORTED_PROTOCOLS = ("sunspec", "modbus", "mqtt")

    def __init__(self, protocol: str = "sunspec") -> None:
        self.protocol = protocol

    def build_pv_available_kw(
        self,
        interval_index: IntervalIndex,
    ) -> pd.Series:
        raise NotImplementedError(
            f"Measured inverter PV via {self.protocol!r} is not implemented. "
            f"Inverter telemetry reports delivered power; recovering "
            f"available power additionally requires a curtailment signal or a "
            f"clear-sky reference, which is not yet modelled."
        )

    def describe(self) -> str:
        return f"Measured inverter {self.protocol} (not implemented)"
