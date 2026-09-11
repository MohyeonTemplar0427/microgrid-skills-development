"""The normalized interval table handed to the optimizer.

One timezone-aware index, one resolution (15 minutes by default), every
timestamp the **start** of its interval.

The user picks an **inclusive** end date in the GUI. Internally the horizon is
half-open, ``start <= timestamp < end``, so the inclusive date is converted by
advancing one calendar day:

    user picks 2026-06-01 .. 2026-06-03 (inclusive)
    internal   2026-06-01 00:00 .. 2026-06-04 00:00 (exclusive)

That advance uses ``DateOffset``, not ``Timedelta``: adding exactly 24 hours
would land at 01:00 local on a daylight-saving day and silently drop or
duplicate an hour.
"""

from dataclasses import dataclass, field

import pandas as pd

from .schema import (
    CARBON_INTENSITY_G_PER_KWH,
    DEFAULT_TIMESTEP_MINUTES,
    LEGACY_TO_CANONICAL,
    MissingDataPolicy,
    NATIVE_LOAD_KW,
    PV_AVAILABLE_KW,
    REQUIRED_COLUMNS,
    TIMESTAMP,
)
from .validation import IntervalTableError, validate_interval_table


@dataclass(frozen=True)
class IntervalIndex:
    """The timezone-aware interval grid for one analysis horizon."""

    start: pd.Timestamp
    end: pd.Timestamp
    timestep_minutes: int
    timezone: str
    index: pd.DatetimeIndex
    inclusive_end_date: str

    @property
    def interval_count(self) -> int:
        return len(self.index)

    @property
    def timestep_hours(self) -> float:
        return self.timestep_minutes / 60.0

    @property
    def billing_days(self) -> float:
        """Number of local calendar dates represented by the interval grid.

        A daylight-saving day can contain 23 or 25 elapsed hours but is still
        one operating and billing day.
        """

        return float(len(self.index.normalize().unique()))


def build_interval_index(
    start_date: str,
    end_date: str,
    timezone: str,
    timestep_minutes: int = DEFAULT_TIMESTEP_MINUTES,
) -> IntervalIndex:
    """Build the interval grid from an **inclusive** end date.

    ``end_date`` is the last day the user wants analysed, and is included in
    full.
    """

    if not timezone:
        raise IntervalTableError(
            "A named timezone is required to build an interval index."
        )

    if timestep_minutes <= 0:
        raise IntervalTableError("timestep_minutes must be positive.")

    if (24 * 60) % timestep_minutes != 0:
        raise IntervalTableError(
            f"timestep_minutes must divide evenly into 24 hours; received "
            f"{timestep_minutes}."
        )

    try:
        start = pd.Timestamp(start_date, tz=timezone)
        inclusive_end = pd.Timestamp(end_date, tz=timezone)
    except Exception as error:
        raise IntervalTableError(
            f"Could not interpret {start_date!r}..{end_date!r} in timezone "
            f"{timezone!r}."
        ) from error

    if inclusive_end < start:
        raise IntervalTableError(
            f"End date {end_date} is before start date {start_date}."
        )

    exclusive_end = inclusive_end + pd.DateOffset(days=1)

    index = pd.date_range(
        start=start,
        end=exclusive_end,
        freq=f"{timestep_minutes}min",
        inclusive="left",
    )

    if len(index) == 0:
        raise IntervalTableError(
            f"Horizon {start}..{exclusive_end} produced no intervals."
        )

    return IntervalIndex(
        start=start,
        end=exclusive_end,
        timestep_minutes=timestep_minutes,
        timezone=timezone,
        index=index,
        inclusive_end_date=str(end_date),
    )


def build_interval_index_from_days(
    start_date: str,
    number_of_days: int,
    timezone: str,
    timestep_minutes: int = DEFAULT_TIMESTEP_MINUTES,
) -> IntervalIndex:
    """Day-count form of :func:`build_interval_index`, for existing callers."""

    if number_of_days <= 0:
        raise IntervalTableError("number_of_days must be positive.")

    inclusive_end = (
        pd.Timestamp(start_date)
        + pd.DateOffset(days=number_of_days - 1)
    ).strftime("%Y-%m-%d")

    return build_interval_index(
        start_date,
        inclusive_end,
        timezone,
        timestep_minutes,
    )


@dataclass
class NormalizedIntervalTable:
    """A validated interval table plus the provenance of how it was built."""

    data: pd.DataFrame
    interval_index: IntervalIndex
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT
    filled_interval_count: int = 0
    source_notes: dict[str, str] = field(default_factory=dict)

    @property
    def timestep_hours(self) -> float:
        return self.interval_index.timestep_hours

    @property
    def contains_filled_data(self) -> bool:
        return self.filled_interval_count > 0

    def to_legacy_frame(self) -> pd.DataFrame:
        """Render in the legacy column names existing dispatch code expects."""

        return to_legacy_columns(self.data)


def align_to_index(
    data: pd.DataFrame,
    interval_index: IntervalIndex,
    *,
    label: str,
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT,
) -> tuple[pd.DataFrame, int]:
    """Clip and reindex ``data`` onto the interval grid.

    Returns the aligned frame and the number of intervals that had to be
    filled. Filling only happens under an explicit non-reject policy, and the
    count is reported so a filled interval is never silently presented as
    measured.
    """

    if TIMESTAMP not in data.columns:
        raise IntervalTableError(f"{label} is missing a timestamp column.")

    timestamps = data[TIMESTAMP]

    if timestamps.dt.tz is None:
        raise IntervalTableError(
            f"{label} timestamps are not timezone-aware."
        )

    aligned = data.copy()
    aligned[TIMESTAMP] = timestamps.dt.tz_convert(interval_index.timezone)

    aligned = (
        aligned.loc[
            (aligned[TIMESTAMP] >= interval_index.start)
            & (aligned[TIMESTAMP] < interval_index.end)
        ]
        .sort_values(TIMESTAMP)
        .reset_index(drop=True)
    )

    if not aligned[TIMESTAMP].is_unique:
        raise IntervalTableError(
            f"{label} contains duplicate timestamps within the horizon."
        )

    present = pd.DatetimeIndex(aligned[TIMESTAMP])
    missing = interval_index.index.difference(present)

    if len(missing) == 0:
        return aligned, 0

    if missing_data_policy == MissingDataPolicy.REJECT:
        raise IntervalTableError(
            f"{label} is missing {len(missing)} of "
            f"{interval_index.interval_count} intervals, first at "
            f"{missing[0]}. Supply complete data, or choose an explicit "
            f"missing-data policy "
            f"({[p.value for p in MissingDataPolicy if p != MissingDataPolicy.REJECT]})."
        )

    reindexed = (
        aligned.set_index(TIMESTAMP)
        .reindex(interval_index.index)
    )

    if missing_data_policy == MissingDataPolicy.FORWARD_FILL:
        reindexed = reindexed.ffill().bfill()
    elif missing_data_policy == MissingDataPolicy.INTERPOLATE:
        reindexed = reindexed.interpolate(method="time").ffill().bfill()
    elif missing_data_policy == MissingDataPolicy.ZERO_FILL:
        reindexed = reindexed.fillna(0.0)

    if reindexed.isna().any().any():
        raise IntervalTableError(
            f"{label} still has missing values after applying the "
            f"{missing_data_policy.value} policy."
        )

    filled = (
        reindexed.reset_index()
        .rename(columns={"index": TIMESTAMP})
    )

    return filled, len(missing)


def build_normalized_table(
    interval_index: IntervalIndex,
    *,
    native_load_kw: pd.Series | pd.DataFrame,
    pv_available_kw: pd.Series | pd.DataFrame,
    price_per_kWh: pd.Series | pd.DataFrame,
    carbon_intensity_g_per_kWh: pd.Series | pd.DataFrame,
    flexible_load_available_kw=None,
    export_limit_kw=None,
    export_price_per_kWh=None,
    rated_pv_capacity_kw: float | None = None,
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT,
    source_notes: dict[str, str] | None = None,
) -> NormalizedIntervalTable:
    """Assemble and validate the table the optimizer consumes."""

    table = pd.DataFrame({TIMESTAMP: interval_index.index})

    columns = {
        NATIVE_LOAD_KW: native_load_kw,
        PV_AVAILABLE_KW: pv_available_kw,
        "price_per_kWh": price_per_kWh,
        CARBON_INTENSITY_G_PER_KWH: carbon_intensity_g_per_kWh,
        "flexible_load_available_kw": flexible_load_available_kw,
        "export_limit_kw": export_limit_kw,
        "export_price_per_kWh": export_price_per_kWh,
    }

    filled_timestamps: set[pd.Timestamp] = set()

    for name, values in columns.items():
        if values is None:
            continue

        aligned_values, filled_for_column = _as_aligned_values(
            values,
            interval_index,
            label=name,
            missing_data_policy=missing_data_policy,
        )
        table[name] = aligned_values
        filled_timestamps.update(filled_for_column)

    validate_interval_table(
        table,
        timestep_minutes=interval_index.timestep_minutes,
        rated_pv_capacity_kw=rated_pv_capacity_kw,
    )

    return NormalizedIntervalTable(
        data=table,
        interval_index=interval_index,
        missing_data_policy=missing_data_policy,
        filled_interval_count=len(filled_timestamps),
        source_notes=dict(source_notes or {}),
    )


def _as_aligned_values(
    values,
    interval_index: IntervalIndex,
    *,
    label: str,
    missing_data_policy: MissingDataPolicy,
):
    """Accept a scalar, a bare series, or a timestamped frame."""

    if isinstance(values, (int, float)):
        return float(values), set()

    if isinstance(values, pd.DataFrame):
        value_columns = [
            column for column in values.columns if column != TIMESTAMP
        ]

        if len(value_columns) != 1:
            raise IntervalTableError(
                f"{label} frame must hold exactly one value column besides "
                f"the timestamp; found {value_columns}."
            )

        source_timestamps = pd.DatetimeIndex(values[TIMESTAMP])

        if source_timestamps.tz is not None:
            source_timestamps = source_timestamps.tz_convert(
                interval_index.timezone
            )

        missing_timestamps = set(
            interval_index.index.difference(source_timestamps)
        )

        aligned, _ = align_to_index(
            values,
            interval_index,
            label=label,
            missing_data_policy=missing_data_policy,
        )
        return aligned[value_columns[0]].to_numpy(), missing_timestamps

    series = pd.Series(values)

    if len(series) != interval_index.interval_count:
        raise IntervalTableError(
            f"{label} has {len(series)} values but the horizon has "
            f"{interval_index.interval_count} intervals."
        )

    return series.to_numpy(), set()


## Compatibility adapters --------------------------------------------------


def from_legacy_columns(data: pd.DataFrame) -> pd.DataFrame:
    """Rename a legacy frame into canonical column names.

    ``load_kw`` becomes ``native_load_kw`` and ``pv_kw`` becomes
    ``pv_available_kw``. In the legacy integrated schema ``pv_kw`` held the PV
    that was assumed to be delivered, with no curtailment concept, which is
    equivalent to available PV under an always-absorbed assumption.
    """

    renamed = data.rename(
        columns={
            legacy: canonical
            for legacy, canonical in LEGACY_TO_CANONICAL.items()
            if legacy in data.columns and canonical not in data.columns
        }
    )

    return renamed


def to_legacy_columns(data: pd.DataFrame) -> pd.DataFrame:
    """Render canonical columns under their legacy names.

    ``net_load_kw`` is recomputed rather than carried, because it is a derived
    quantity: native load minus available PV.
    """

    legacy = data.copy()

    if NATIVE_LOAD_KW in legacy.columns:
        legacy["load_kw"] = legacy[NATIVE_LOAD_KW]

    if PV_AVAILABLE_KW in legacy.columns:
        legacy["pv_kw"] = legacy[PV_AVAILABLE_KW]

    if CARBON_INTENSITY_G_PER_KWH in legacy.columns:
        legacy["gCO2/kWh"] = legacy[CARBON_INTENSITY_G_PER_KWH]

    if {"load_kw", "pv_kw"}.issubset(legacy.columns):
        legacy["net_load_kw"] = legacy["load_kw"] - legacy["pv_kw"]

    return legacy


def normalize_any_frame(
    data: pd.DataFrame,
    *,
    timestep_minutes: int = DEFAULT_TIMESTEP_MINUTES,
    rated_pv_capacity_kw: float | None = None,
) -> pd.DataFrame:
    """Accept either schema and return a validated canonical frame."""

    canonical = from_legacy_columns(data)

    missing = [
        column
        for column in REQUIRED_COLUMNS
        if column not in canonical.columns
    ]

    if missing:
        raise IntervalTableError(
            f"Frame is missing {missing} in both canonical and legacy form. "
            f"Received: {sorted(data.columns)}."
        )

    validate_interval_table(
        canonical,
        timestep_minutes=timestep_minutes,
        rated_pv_capacity_kw=rated_pv_capacity_kw,
    )

    return canonical
