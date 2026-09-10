"""Day-based analysis horizons.

The frontend supplies ``start_date``, ``number_of_days``, ``timestep_minutes``
and ``timezone``. This module turns those into a half-open, timezone-aware
interval index:

    start <= timestamp < end

The expected interval count is read off that index, never computed as
``number_of_days * 96``. A local day containing a daylight-saving transition
is 23 or 25 hours long, so it holds 92 or 100 fifteen-minute intervals.
"""

from dataclasses import dataclass

import pandas as pd

from .providers.base import (
    DuplicateIntervalError,
    MissingIntervalError,
    TimezoneNormalizationError,
)


@dataclass(frozen=True)
class AnalysisHorizon:
    """A resolved, timezone-aware analysis window."""

    start: pd.Timestamp
    end: pd.Timestamp
    timestep_minutes: int
    timezone: str
    number_of_days: int
    index: pd.DatetimeIndex

    @property
    def interval_count(self) -> int:
        """Number of intervals actually in the window."""

        return len(self.index)

    @property
    def timestep_hours(self) -> float:
        return self.timestep_minutes / 60.0

    @property
    def intervals_per_regular_day(self) -> int:
        return 24 * 60 // self.timestep_minutes

    def contains_dst_transition(self) -> bool:
        """True when the window is not a whole number of 24-hour days."""

        regular_intervals = (
            self.number_of_days * self.intervals_per_regular_day
        )

        return self.interval_count != regular_intervals


def build_horizon(
    start_date: str,
    number_of_days: int,
    timezone: str,
    timestep_minutes: int = 15,
) -> AnalysisHorizon:
    """Build the interval index for ``number_of_days`` local days."""

    if not timezone:
        raise TimezoneNormalizationError(
            "A named timezone is required to build an analysis horizon."
        )

    if number_of_days <= 0:
        raise ValueError("number_of_days must be positive.")

    if timestep_minutes <= 0:
        raise ValueError("timestep_minutes must be positive.")

    if (24 * 60) % timestep_minutes != 0:
        raise ValueError(
            f"timestep_minutes must divide evenly into 24 hours; "
            f"received {timestep_minutes}."
        )

    try:
        start = pd.Timestamp(start_date, tz=timezone)
    except Exception as error:
        raise TimezoneNormalizationError(
            f"Could not interpret {start_date!r} in timezone {timezone!r}."
        ) from error

    # DateOffset advances the wall-clock calendar day; Timedelta would add
    # exactly 24 hours and land at 01:00 on a spring-forward day.
    end = start + pd.DateOffset(days=number_of_days)

    index = pd.date_range(
        start=start,
        end=end,
        freq=f"{timestep_minutes}min",
        inclusive="left",
    )

    if len(index) == 0:
        raise ValueError(
            f"Horizon {start} to {end} produced no intervals."
        )

    return AnalysisHorizon(
        start=start,
        end=end,
        timestep_minutes=timestep_minutes,
        timezone=timezone,
        number_of_days=number_of_days,
        index=index,
    )


def align_to_horizon(
    data: pd.DataFrame,
    horizon: AnalysisHorizon,
    *,
    label: str,
) -> pd.DataFrame:
    """Clip ``data`` to the horizon and verify it covers every interval."""

    if "timestamp" not in data.columns:
        raise ValueError(f"{label} data is missing a timestamp column.")

    timestamps = data["timestamp"]

    if timestamps.dt.tz is None:
        raise TimezoneNormalizationError(
            f"{label} timestamps are not timezone-aware."
        )

    aligned = data.loc[
        (timestamps >= horizon.start) & (timestamps < horizon.end)
    ].copy()

    aligned = aligned.sort_values("timestamp").reset_index(drop=True)

    if not aligned["timestamp"].is_unique:
        raise DuplicateIntervalError(
            f"{label} data contains duplicate timestamps."
        )

    missing = horizon.index.difference(
        pd.DatetimeIndex(aligned["timestamp"])
    )

    if len(missing) > 0:
        raise MissingIntervalError(
            f"{label} data is missing {len(missing)} of "
            f"{horizon.interval_count} intervals, starting at {missing[0]}."
        )

    return aligned


def combine_chunks_strictly(
    frames: list[pd.DataFrame],
    *,
    value_columns: tuple[str, ...],
    label: str,
) -> pd.DataFrame:
    """Join chunks, dropping identical boundary rows but rejecting conflicts.

    Providers whose ``end`` is inclusive repeat the boundary interval in the
    next chunk. An exact repeat is dropped; the same timestamp carrying a
    *different* value means the chunks disagree and is an error rather than
    something to silently pick a winner for.
    """

    populated = [frame for frame in frames if len(frame) > 0]

    if not populated:
        raise ValueError(f"{label} produced no rows to combine.")

    combined = pd.concat(populated, ignore_index=True)

    combined = combined.sort_values("timestamp").reset_index(drop=True)

    duplicated = combined.duplicated(subset="timestamp", keep=False)

    if duplicated.any():
        conflicting = (
            combined.loc[duplicated]
            .groupby("timestamp")[list(value_columns)]
            .nunique()
            .gt(1)
            .any(axis=1)
        )

        if conflicting.any():
            first_conflict = conflicting.index[conflicting][0]
            raise ValueError(
                f"{label} chunks disagree at {first_conflict}: the same "
                f"interval was returned with different values."
            )

    combined = (
        combined.drop_duplicates(subset="timestamp", keep="first")
        .reset_index(drop=True)
    )

    return combined
