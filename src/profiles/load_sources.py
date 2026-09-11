"""Load-profile sources.

Every source produces ``native_load_kw`` -- site demand **before** PV and
battery effects -- on the analysis interval grid.

Synthetic profiles are shape demonstrations, not measured data. They carry
``is_synthetic = True`` so the GUI and reports can label them, because a
plausible-looking shape is easy to mistake for a real meter trace.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
import pandas as pd

from ..timeseries.interval_table import IntervalIndex, align_to_index
from ..timeseries.schema import MissingDataPolicy, PowerUnit, convert_to_kw
from ..timeseries.validation import IntervalTableError


class LoadSourceMode(StrEnum):
    CONSTANT = "constant"
    SYNTHETIC = "synthetic"
    CSV = "csv"
    MEASURED = "measured"


class BuildingArchetype(StrEnum):
    RESIDENTIAL = "residential"
    MULTIFAMILY = "multifamily"
    OFFICE = "office"
    RETAIL = "retail"
    SCHOOL = "school"
    INDUSTRIAL = "industrial"


class LoadScaling(StrEnum):
    """Which quantity the user pins when scaling a normalized shape."""

    PEAK_KW = "peak_kw"
    DAILY_ENERGY_KWH = "daily_energy_kWh"


class LoadSourceError(ValueError):
    pass


# Normalized 24-hour shapes, one value per hour, peak-normalized to 1.0.
# These are stylized demonstration shapes, not calibrated building models.
_WEEKDAY_SHAPES: dict[BuildingArchetype, tuple[float, ...]] = {
    BuildingArchetype.RESIDENTIAL: (
        0.35, 0.31, 0.29, 0.28, 0.29, 0.34, 0.48, 0.62,
        0.58, 0.48, 0.42, 0.40, 0.39, 0.39, 0.41, 0.47,
        0.62, 0.82, 1.00, 0.95, 0.83, 0.70, 0.55, 0.43,
    ),
    BuildingArchetype.MULTIFAMILY: (
        0.42, 0.38, 0.36, 0.35, 0.36, 0.41, 0.53, 0.64,
        0.61, 0.54, 0.49, 0.47, 0.46, 0.46, 0.48, 0.54,
        0.66, 0.84, 1.00, 0.94, 0.84, 0.73, 0.60, 0.49,
    ),
    BuildingArchetype.OFFICE: (
        0.22, 0.20, 0.20, 0.20, 0.21, 0.26, 0.40, 0.66,
        0.86, 0.95, 0.98, 1.00, 0.96, 0.97, 0.97, 0.93,
        0.85, 0.66, 0.45, 0.34, 0.29, 0.26, 0.24, 0.23,
    ),
    BuildingArchetype.RETAIL: (
        0.24, 0.22, 0.21, 0.21, 0.22, 0.26, 0.35, 0.50,
        0.68, 0.83, 0.92, 0.97, 1.00, 1.00, 0.98, 0.95,
        0.92, 0.88, 0.82, 0.72, 0.57, 0.42, 0.32, 0.27,
    ),
    BuildingArchetype.SCHOOL: (
        0.18, 0.17, 0.16, 0.16, 0.17, 0.23, 0.42, 0.72,
        0.93, 1.00, 1.00, 0.98, 0.94, 0.92, 0.86, 0.70,
        0.48, 0.35, 0.29, 0.26, 0.23, 0.21, 0.20, 0.19,
    ),
    BuildingArchetype.INDUSTRIAL: (
        0.62, 0.61, 0.60, 0.60, 0.61, 0.66, 0.80, 0.93,
        0.98, 1.00, 1.00, 0.99, 0.95, 0.98, 0.99, 0.97,
        0.92, 0.85, 0.78, 0.73, 0.70, 0.68, 0.65, 0.63,
    ),
}

# Weekend behaviour as a scale factor and a flattening weight per archetype.
# Residential rises at weekends; commercial and institutional loads fall.
_WEEKEND_FACTORS: dict[BuildingArchetype, float] = {
    BuildingArchetype.RESIDENTIAL: 1.08,
    BuildingArchetype.MULTIFAMILY: 1.05,
    BuildingArchetype.OFFICE: 0.38,
    BuildingArchetype.RETAIL: 0.78,
    BuildingArchetype.SCHOOL: 0.22,
    BuildingArchetype.INDUSTRIAL: 0.55,
}


class LoadProfileSource(ABC):
    """Produces ``native_load_kw`` over an interval index."""

    mode: LoadSourceMode
    is_synthetic: bool = False

    @abstractmethod
    def build_load_kw(self, interval_index: IntervalIndex) -> pd.Series:
        """Return one kW value per interval, indexed positionally."""

    def describe(self) -> str:
        return self.mode.value


@dataclass
class ConstantLoad(LoadProfileSource):
    """A single flat kW demand for every interval."""

    load_kw: float

    mode = LoadSourceMode.CONSTANT

    def __post_init__(self) -> None:
        self.load_kw = _validate_power(self.load_kw, "Constant load")

    def build_load_kw(self, interval_index: IntervalIndex) -> pd.Series:
        return pd.Series(
            np.full(interval_index.interval_count, self.load_kw),
            name="native_load_kw",
        )

    def describe(self) -> str:
        return f"Constant {self.load_kw:.2f} kW"


@dataclass
class SyntheticLoad(LoadProfileSource):
    """A stylized archetype shape scaled to a peak or a daily energy.

    Variability, when enabled, is drawn from a seeded generator so a rerun of
    the same configuration reproduces the same profile exactly.
    """

    archetype: BuildingArchetype
    scaling: LoadScaling = LoadScaling.PEAK_KW
    peak_kw: float | None = None
    daily_energy_kWh: float | None = None
    variability_fraction: float = 0.0
    random_seed: int = 20260101

    mode = LoadSourceMode.SYNTHETIC
    is_synthetic = True

    def __post_init__(self) -> None:
        self.archetype = BuildingArchetype(self.archetype)
        self.scaling = LoadScaling(self.scaling)

        if self.scaling == LoadScaling.PEAK_KW:
            if self.peak_kw is None:
                raise LoadSourceError(
                    "Peak-scaled synthetic load requires peak_kw."
                )
            self.peak_kw = _validate_power(self.peak_kw, "Peak load")
        else:
            if self.daily_energy_kWh is None:
                raise LoadSourceError(
                    "Energy-scaled synthetic load requires daily_energy_kWh."
                )
            self.daily_energy_kWh = _validate_power(
                self.daily_energy_kWh,
                "Daily energy",
            )

        if not 0.0 <= self.variability_fraction <= 1.0:
            raise LoadSourceError(
                f"variability_fraction must be between 0 and 1; received "
                f"{self.variability_fraction}."
            )

    def build_load_kw(self, interval_index: IntervalIndex) -> pd.Series:
        timestamps = interval_index.index

        weekday_shape = np.array(_WEEKDAY_SHAPES[self.archetype])
        weekend_factor = _WEEKEND_FACTORS[self.archetype]

        hours = timestamps.hour.to_numpy()
        is_weekend = timestamps.dayofweek.to_numpy() >= 5

        shape = weekday_shape[hours]
        # Weekends scale toward the archetype's weekend level while flattening
        # halfway to the daily mean, since occupancy patterns are less peaked.
        weekend_shape = (
            weekend_factor
            * (shape + weekday_shape.mean()) / 2.0
        )
        shape = np.where(is_weekend, weekend_shape, shape)

        if self.variability_fraction > 0:
            generator = np.random.default_rng(self.random_seed)
            noise = generator.normal(
                loc=1.0,
                scale=self.variability_fraction,
                size=shape.shape,
            )
            shape = shape * np.clip(noise, 0.0, None)

        values = self._scale(shape, interval_index)

        return pd.Series(values, name="native_load_kw")

    def _scale(self, shape: np.ndarray, interval_index: IntervalIndex):
        if self.scaling == LoadScaling.PEAK_KW:
            # The archetype shapes are already normalized so that the weekday
            # peak is 1.0. Scaling by peak_kw directly keeps weekend days
            # proportionally lower; renormalizing against the horizon's own
            # maximum would inflate a weekend-only horizon back to peak_kw.
            return shape * self.peak_kw

        total_energy_kWh = (
            shape.sum() * interval_index.timestep_hours
        )

        if total_energy_kWh <= 0:
            raise LoadSourceError("Synthetic load shape collapsed to zero.")

        horizon_days = interval_index.billing_days
        target_energy_kWh = self.daily_energy_kWh * horizon_days

        return shape * (target_energy_kWh / total_energy_kWh)

    def describe(self) -> str:
        basis = (
            f"peak {self.peak_kw:.2f} kW"
            if self.scaling == LoadScaling.PEAK_KW
            else f"{self.daily_energy_kWh:.2f} kWh/day"
        )
        return (
            f"Synthetic {self.archetype.value} ({basis}, seed "
            f"{self.random_seed}) - SYNTHETIC DATA"
        )


@dataclass
class CSVLoad(LoadProfileSource):
    """Load read from a user-supplied table."""

    data: pd.DataFrame
    timestamp_column: str = "timestamp"
    load_column: str = "load_kw"
    unit: PowerUnit | str = PowerUnit.KW
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT
    filled_interval_count: int = field(default=0, init=False)

    mode = LoadSourceMode.CSV

    def build_load_kw(self, interval_index: IntervalIndex) -> pd.Series:
        frame = _prepare_csv_frame(
            self.data,
            self.timestamp_column,
            self.load_column,
            label="Load CSV",
        )

        frame["value_kw"] = convert_to_kw(frame["value"], self.unit)

        aligned, filled = align_to_index(
            frame[["timestamp", "value_kw"]],
            interval_index,
            label="Load CSV",
            missing_data_policy=self.missing_data_policy,
        )

        self.filled_interval_count = filled

        values = aligned["value_kw"].to_numpy(dtype=float)

        if (values < 0).any():
            raise LoadSourceError(
                "Load CSV contains negative values. Native load is demand "
                "before PV, so it cannot be negative; a site that exports is "
                "modelled through PV and export, not negative load."
            )

        return pd.Series(values, name="native_load_kw")

    def describe(self) -> str:
        note = (
            f", {self.filled_interval_count} intervals filled by "
            f"{self.missing_data_policy.value}"
            if self.filled_interval_count
            else ""
        )
        return f"CSV column {self.load_column!r} ({self.unit}){note}"


class MeasuredLoadAdapter(LoadProfileSource):
    """Extension point for live metered load.

    **Not implemented.** Green Button, Modbus, SunSpec and MQTT integrations
    would each subclass this and implement :meth:`build_load_kw`. No hardware
    connection exists; calling this raises rather than returning fabricated
    data, so a future GUI entry cannot silently produce invented numbers.
    """

    mode = LoadSourceMode.MEASURED

    SUPPORTED_PROTOCOLS = (
        "green_button",
        "modbus",
        "sunspec",
        "mqtt",
    )

    def __init__(self, protocol: str = "green_button") -> None:
        self.protocol = protocol

    def build_load_kw(self, interval_index: IntervalIndex) -> pd.Series:
        raise NotImplementedError(
            f"Measured load via {self.protocol!r} is not implemented. This is "
            f"a planned extension point; no hardware or utility-download "
            f"connection exists yet. Use the CSV load source to analyse "
            f"measured data you have already exported."
        )

    def describe(self) -> str:
        return f"Measured {self.protocol} (not implemented)"


def _validate_power(value, label: str) -> float:
    try:
        power = float(value)
    except (TypeError, ValueError) as error:
        raise LoadSourceError(
            f"{label} must be a number; received {value!r}."
        ) from error

    if not np.isfinite(power):
        raise LoadSourceError(f"{label} must be finite; received {value!r}.")

    if power < 0:
        raise LoadSourceError(
            f"{label} must not be negative; received {power}."
        )

    return power


def _prepare_csv_frame(
    data: pd.DataFrame,
    timestamp_column: str,
    value_column: str,
    *,
    label: str,
) -> pd.DataFrame:
    """Pull the chosen timestamp and value columns into a standard frame."""

    if data is None or len(data) == 0:
        raise LoadSourceError(f"{label} is empty.")

    missing = {timestamp_column, value_column} - set(data.columns)

    if missing:
        raise LoadSourceError(
            f"{label} is missing columns {sorted(missing)}. "
            f"Available columns: {sorted(data.columns)}."
        )

    frame = pd.DataFrame(
        {
            "timestamp": data[timestamp_column],
            "value": data[value_column],
        }
    )

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")

    if frame["timestamp"].isna().any():
        raise LoadSourceError(
            f"{label} column {timestamp_column!r} contains unparseable "
            f"timestamps."
        )

    if frame["timestamp"].dt.tz is None:
        raise IntervalTableError(
            f"{label} timestamps are timezone-naive. Localize them to the "
            f"analysis timezone before use, so daylight-saving transitions "
            f"are unambiguous."
        )

    try:
        frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    except (TypeError, ValueError) as error:
        raise LoadSourceError(
            f"{label} column {value_column!r} contains nonnumeric values."
        ) from error

    return frame
