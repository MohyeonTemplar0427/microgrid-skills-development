"""Provider-neutral contract for market price retrieval.

Every adapter returns the same normalized frame:

    timestamp        tz-aware, converted to the configured named timezone
    price_per_kWh    $/kWh

Wholesale ISOs publish LMPs in **$/MWh**. Adapters divide by 1000 exactly
once, in :func:`normalize_price_frame`, so the conversion lives in one place.
"""

from abc import ABC, abstractmethod

import pandas as pd

PRICE_COLUMNS = (
    "timestamp",
    "price_per_kWh",
)

DOLLARS_PER_MWH_TO_DOLLARS_PER_KWH = 1 / 1000

TARGET_INTERVAL_MINUTES = 15


class SignalProviderError(Exception):
    """Base class for every signal-pipeline retrieval failure."""


class UnsupportedProviderError(SignalProviderError):
    pass


class UnknownRegionError(SignalProviderError):
    pass


class MissingCredentialsError(SignalProviderError):
    pass


class InvalidLocationError(SignalProviderError):
    pass


class EmptyResponseError(SignalProviderError):
    pass


class SchemaError(SignalProviderError):
    pass


class UnitConversionError(SignalProviderError):
    pass


class TimezoneNormalizationError(SignalProviderError):
    pass


class DuplicateIntervalError(SignalProviderError):
    pass


class MissingIntervalError(SignalProviderError):
    pass


class RangeLimitError(SignalProviderError):
    pass


class MarketProvider(ABC):
    """Adapter for one wholesale market's price API."""

    name: str
    default_timezone: str
    source_price_unit: str = "$/MWh"
    native_interval_minutes: int
    max_chunk_days: int | None = None
    archive_limit_days: int | None = None
    requires_credentials: bool = False
    credential_env_var: str | None = None

    @abstractmethod
    def fetch_energy_prices(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        location: str,
    ) -> pd.DataFrame:
        """Return normalized prices for ``[start_time, end_time)``.

        Timestamps must be tz-aware. The returned frame carries exactly
        :data:`PRICE_COLUMNS`.
        """


def require_aware_timestamps(
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    timezone: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Coerce a request window into tz-aware timestamps in ``timezone``."""

    try:
        start = pd.Timestamp(start_time)
        end = pd.Timestamp(end_time)
    except (TypeError, ValueError) as error:
        raise TimezoneNormalizationError(
            f"Could not interpret the request window "
            f"({start_time!r}, {end_time!r})."
        ) from error

    try:
        start = (
            start.tz_localize(timezone)
            if start.tzinfo is None
            else start.tz_convert(timezone)
        )
        end = (
            end.tz_localize(timezone)
            if end.tzinfo is None
            else end.tz_convert(timezone)
        )
    except Exception as error:
        raise TimezoneNormalizationError(
            f"Could not localize the request window to {timezone}."
        ) from error

    if end <= start:
        raise RangeLimitError(
            f"end_time ({end}) must be after start_time ({start})."
        )

    return start, end


def normalize_price_frame(
    raw_data: pd.DataFrame,
    *,
    provider_name: str,
    timestamp_column: str,
    price_column: str,
    timezone: str,
) -> pd.DataFrame:
    """Rename, convert $/MWh to $/kWh, and move timestamps into ``timezone``."""

    if raw_data is None or len(raw_data) == 0:
        raise EmptyResponseError(
            f"{provider_name} returned no rows for the requested window."
        )

    missing_columns = {
        timestamp_column,
        price_column,
    } - set(raw_data.columns)

    if missing_columns:
        raise SchemaError(
            f"{provider_name} response is missing required columns: "
            f"{sorted(missing_columns)}. Received: {sorted(raw_data.columns)}."
        )

    data = raw_data[[timestamp_column, price_column]].copy()

    data = data.rename(
        columns={
            timestamp_column: "timestamp",
            price_column: "price_per_kWh",
        }
    )

    data["timestamp"] = pd.to_datetime(
        data["timestamp"],
        errors="coerce",
    )

    if data["timestamp"].isna().any():
        raise SchemaError(
            f"{provider_name} returned unparseable timestamps."
        )

    try:
        if data["timestamp"].dt.tz is None:
            data["timestamp"] = data["timestamp"].dt.tz_localize("UTC")

        data["timestamp"] = data["timestamp"].dt.tz_convert(timezone)
    except Exception as error:
        raise TimezoneNormalizationError(
            f"Could not convert {provider_name} timestamps to {timezone}."
        ) from error

    try:
        prices = pd.to_numeric(
            data["price_per_kWh"],
            errors="raise",
        )
    except (TypeError, ValueError) as error:
        raise UnitConversionError(
            f"{provider_name} returned nonnumeric prices; "
            f"cannot convert $/MWh to $/kWh."
        ) from error

    data["price_per_kWh"] = (
        prices * DOLLARS_PER_MWH_TO_DOLLARS_PER_KWH
    )

    data = (
        data.sort_values("timestamp")
        .reset_index(drop=True)
    )

    return data[list(PRICE_COLUMNS)]


def iterate_chunks(
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    max_chunk_days: int | None,
):
    """Split ``[start_time, end_time)`` into half-open provider-sized chunks.

    Half-open chunks are what keep boundary intervals from being fetched
    twice; :func:`combine_chunks` still de-duplicates because providers
    differ on whether their own ``end`` is inclusive.
    """

    if max_chunk_days is None:
        yield start_time, end_time
        return

    span = pd.Timedelta(days=max_chunk_days)
    chunk_start = start_time

    while chunk_start < end_time:
        chunk_end = min(chunk_start + span, end_time)
        yield chunk_start, chunk_end
        chunk_start = chunk_end


def combine_chunks(
    frames: list[pd.DataFrame],
    *,
    provider_name: str,
) -> pd.DataFrame:
    """Concatenate chunk results, dropping repeated boundary intervals."""

    populated = [frame for frame in frames if len(frame) > 0]

    if not populated:
        raise EmptyResponseError(
            f"{provider_name} returned no rows for the requested window."
        )

    combined = pd.concat(populated, ignore_index=True)

    combined = (
        combined.sort_values("timestamp")
        .drop_duplicates(subset="timestamp", keep="first")
        .reset_index(drop=True)
    )

    return combined


def trim_to_window(
    data: pd.DataFrame,
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
) -> pd.DataFrame:
    """Clip to the half-open window ``[start_time, end_time)``.

    Providers disagree on whether their ``end`` is inclusive; PJM returns the
    interval that lands exactly on ``end``, which belongs to the next window.
    """

    within_window = (
        (data["timestamp"] >= start_time)
        & (data["timestamp"] < end_time)
    )

    return data.loc[within_window].reset_index(drop=True)


def resample_to_target_interval(
    data: pd.DataFrame,
    *,
    native_interval_minutes: int,
    provider_name: str,
    target_interval_minutes: int = TARGET_INTERVAL_MINUTES,
) -> pd.DataFrame:
    """Average sub-interval prices up to the pipeline's 15-minute grid.

    A plain mean is the correct time-weighted average here only because the
    native intervals are equal-duration (PJM's 5-minute LMPs).
    """

    if native_interval_minutes == target_interval_minutes:
        return data

    if native_interval_minutes > target_interval_minutes:
        raise RangeLimitError(
            f"{provider_name} publishes {native_interval_minutes}-minute "
            f"intervals, which cannot be upsampled to "
            f"{target_interval_minutes} minutes without inventing data."
        )

    if target_interval_minutes % native_interval_minutes != 0:
        raise RangeLimitError(
            f"{provider_name}'s {native_interval_minutes}-minute intervals "
            f"do not divide evenly into {target_interval_minutes} minutes."
        )

    resampled = (
        data.set_index("timestamp")["price_per_kWh"]
        .resample(f"{target_interval_minutes}min")
        .mean()
        .dropna()
        .reset_index()
    )

    if resampled.empty:
        raise EmptyResponseError(
            f"{provider_name} data was empty after resampling to "
            f"{target_interval_minutes}-minute intervals."
        )

    return resampled


def check_intervals(
    data: pd.DataFrame,
    *,
    provider_name: str,
    interval_minutes: int = TARGET_INTERVAL_MINUTES,
) -> None:
    """Reject duplicates and report gaps in the interval sequence.

    Gap detection walks the observed timestamps rather than assuming a fixed
    count per day, so daylight-saving transitions (23- and 25-hour local days)
    pass unchanged.
    """

    timestamps = data["timestamp"]

    if timestamps.dt.tz is None:
        raise TimezoneNormalizationError(
            f"{provider_name} timestamps are not timezone-aware."
        )

    if not timestamps.is_unique:
        duplicates = timestamps[timestamps.duplicated()].unique()
        raise DuplicateIntervalError(
            f"{provider_name} returned duplicate intervals: "
            f"{list(duplicates)[:5]}."
        )

    if not timestamps.is_monotonic_increasing:
        raise MissingIntervalError(
            f"{provider_name} timestamps are not in increasing order."
        )

    expected_step = pd.Timedelta(minutes=interval_minutes)

    gaps = timestamps.diff().dropna()
    irregular = gaps[gaps != expected_step]

    if not irregular.empty:
        first_gap_position = irregular.index[0]
        raise MissingIntervalError(
            f"{provider_name} data has a gap before "
            f"{timestamps.iloc[first_gap_position]}: expected "
            f"{expected_step}, found {irregular.iloc[0]}."
        )
