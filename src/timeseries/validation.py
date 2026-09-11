"""Validation for the normalized interval table.

Pure functions: nothing here renders GUI, orchestrates a simulation, or
fetches data. Each check raises :class:`IntervalTableError` with a message
naming the offending timestamp, so a failure is actionable rather than a bare
"invalid data".
"""

import numpy as np
import pandas as pd

from .schema import (
    CARBON_INTENSITY_G_PER_KWH,
    NATIVE_LOAD_KW,
    POWER_TOLERANCE_KW,
    PV_AVAILABLE_KW,
    REQUIRED_COLUMNS,
    TIMESTAMP,
)


class IntervalTableError(ValueError):
    """The interval table violates a documented invariant."""


def require_columns(
    data: pd.DataFrame,
    columns=REQUIRED_COLUMNS,
    *,
    label: str = "Interval table",
) -> None:
    missing = [column for column in columns if column not in data.columns]

    if missing:
        raise IntervalTableError(
            f"{label} is missing required columns: {missing}. "
            f"Received: {sorted(data.columns)}."
        )


def require_named_timezone(
    data: pd.DataFrame,
    *,
    label: str = "Interval table",
) -> str:
    """Return the table's timezone name, rejecting naive or fixed offsets."""

    timestamps = data[TIMESTAMP]

    if not pd.api.types.is_datetime64_any_dtype(timestamps):
        raise IntervalTableError(
            f"{label} timestamps must use a pandas datetime dtype."
        )

    zone = timestamps.dt.tz

    if zone is None:
        raise IntervalTableError(
            f"{label} timestamps are not timezone-aware."
        )

    name = str(zone)

    # A fixed offset carries no daylight-saving rules, so a local-day horizon
    # cannot be interpreted against it. UTC genuinely has no transitions.
    if name != "UTC" and ("/" not in name or name.startswith("Etc/")):
        raise IntervalTableError(
            f"{label} uses the fixed offset {name!r}. A named IANA timezone "
            f"such as 'America/Los_Angeles' is required so daylight-saving "
            f"transitions are defined."
        )

    return name


def require_regular_intervals(
    data: pd.DataFrame,
    timestep_minutes: int,
    *,
    label: str = "Interval table",
) -> None:
    """Reject duplicates, non-monotonic order and irregular spacing.

    Spacing is checked by walking the observed timestamps, so a
    daylight-saving day with 92 or 100 intervals passes: the wall-clock gap
    between consecutive intervals stays constant even as the day's total
    changes.
    """

    timestamps = data[TIMESTAMP]

    if timestamps.empty:
        raise IntervalTableError(f"{label} is empty.")

    if not timestamps.is_unique:
        duplicates = timestamps[timestamps.duplicated()].unique()
        raise IntervalTableError(
            f"{label} contains duplicate timestamps: {list(duplicates)[:5]}."
        )

    if not timestamps.is_monotonic_increasing:
        raise IntervalTableError(
            f"{label} timestamps are not in increasing order."
        )

    if len(timestamps) == 1:
        return

    expected = pd.Timedelta(minutes=timestep_minutes)
    gaps = timestamps.diff().dropna()
    irregular = gaps[gaps != expected]

    if not irregular.empty:
        position = irregular.index[0]
        raise IntervalTableError(
            f"{label} has irregular spacing before "
            f"{timestamps.iloc[position]}: expected {expected}, found "
            f"{irregular.iloc[0]}."
        )


def require_finite_values(
    data: pd.DataFrame,
    columns,
    *,
    label: str = "Interval table",
) -> None:
    for column in columns:
        if column not in data.columns:
            continue

        try:
            values = pd.to_numeric(data[column], errors="raise")
        except (TypeError, ValueError) as error:
            raise IntervalTableError(
                f"{label} column {column!r} contains nonnumeric values."
            ) from error

        array = values.to_numpy(dtype=float)

        if np.isnan(array).any():
            first = data[TIMESTAMP].iloc[int(np.argmax(np.isnan(array)))]
            raise IntervalTableError(
                f"{label} column {column!r} has a missing value at {first}."
            )

        if not np.isfinite(array).all():
            raise IntervalTableError(
                f"{label} column {column!r} contains non-finite values."
            )


def require_nonnegative(
    data: pd.DataFrame,
    columns,
    *,
    label: str = "Interval table",
) -> None:
    for column in columns:
        if column not in data.columns:
            continue

        values = pd.to_numeric(data[column], errors="coerce")
        negative = values < -POWER_TOLERANCE_KW

        if negative.any():
            first = data[TIMESTAMP].loc[negative.idxmax()]
            raise IntervalTableError(
                f"{label} column {column!r} is negative at {first} "
                f"({values.loc[negative.idxmax()]}). Load and PV availability "
                f"must be nonnegative; a negative net position is expressed "
                f"through grid export, not negative load."
            )


def require_pv_within_rating(
    data: pd.DataFrame,
    rated_pv_capacity_kw: float | None,
    *,
    tolerance_fraction: float = 0.05,
    label: str = "Interval table",
) -> None:
    """Check available PV never materially exceeds the configured rating.

    A small overshoot is allowed because irradiance on cold clear days can
    briefly push a array above its nameplate rating.
    """

    if rated_pv_capacity_kw is None or PV_AVAILABLE_KW not in data.columns:
        return

    if rated_pv_capacity_kw <= 0:
        raise IntervalTableError(
            f"Rated PV capacity must be positive; received "
            f"{rated_pv_capacity_kw}."
        )

    ceiling = rated_pv_capacity_kw * (1 + tolerance_fraction)
    exceeded = data[PV_AVAILABLE_KW] > ceiling

    if exceeded.any():
        first = data[TIMESTAMP].loc[exceeded.idxmax()]
        peak = float(data[PV_AVAILABLE_KW].max())
        raise IntervalTableError(
            f"{label} available PV peaks at {peak:.2f} kW, above the "
            f"{rated_pv_capacity_kw:.2f} kW rating (+{tolerance_fraction:.0%} "
            f"tolerance), first exceeded at {first}. Check the PV column "
            f"units, or whether the file holds capacity factors rather than "
            f"kW."
        )


def validate_interval_table(
    data: pd.DataFrame,
    *,
    timestep_minutes: int,
    rated_pv_capacity_kw: float | None = None,
    label: str = "Interval table",
) -> str:
    """Run every structural check. Returns the table's timezone name."""

    require_columns(data, label=label)
    timezone = require_named_timezone(data, label=label)
    require_regular_intervals(data, timestep_minutes, label=label)

    numeric_columns = [
        column for column in data.columns if column != TIMESTAMP
    ]

    require_finite_values(data, numeric_columns, label=label)
    require_nonnegative(
        data,
        [NATIVE_LOAD_KW, PV_AVAILABLE_KW, CARBON_INTENSITY_G_PER_KWH],
        label=label,
    )
    require_pv_within_rating(
        data,
        rated_pv_capacity_kw,
        label=label,
    )

    return timezone
