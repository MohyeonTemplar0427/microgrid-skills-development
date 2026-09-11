"""Provider-neutral price retrieval.

The public entry point is :func:`fetch_energy_prices`, which returns the
normalized ``timestamp`` / ``price_per_kWh`` schema regardless of which ISO
served the request. Provider-specific quirks live in
:mod:`src.signal_pipeline.providers`.

The ``get_caiso_*`` functions are kept as compatibility wrappers so existing
CAISO callers keep working unchanged.
"""

import gridstatus
import pandas as pd

from .providers import (
    MarketProvider,
    get_provider,
)
from .providers.base import (
    TARGET_INTERVAL_MINUTES,
    DuplicateIntervalError,
    MissingIntervalError,
    TimezoneNormalizationError,
    check_intervals,
    normalize_price_frame,
)
from .region_config import RegionConfig, get_region_config

LOCAL_TIMEZONE = "America/Los_Angeles"


def fetch_energy_prices(
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    location: str,
    *,
    provider: str = "caiso",
    **provider_options,
) -> pd.DataFrame:
    """Retrieve normalized prices from any registered market provider.

    Returns a frame with ``timestamp`` (tz-aware, in the provider's named
    timezone) and ``price_per_kWh`` ($/kWh, converted from the ISO's $/MWh).
    """

    adapter: MarketProvider = get_provider(
        provider,
        **provider_options,
    )

    return adapter.fetch_energy_prices(
        start_time,
        end_time,
        location,
    )


def fetch_region_prices(
    region: str | RegionConfig,
    start_date: str,
    number_of_days: int,
    *,
    sleep_seconds: float = 1.0,
) -> pd.DataFrame:
    """Retrieve prices for a configured region over whole local days.

    The window is built in the region's own timezone, so a day containing a
    daylight-saving transition is 23 or 25 hours long rather than a fixed 24.
    """

    region_config = (
        region
        if isinstance(region, RegionConfig)
        else get_region_config(region)
    )

    start_time = pd.Timestamp(
        start_date,
        tz=region_config.timezone,
    )

    # DateOffset advances local calendar days; Timedelta would add exactly
    # 24 hours and drift by an hour across a daylight-saving transition.
    end_time = start_time + pd.DateOffset(days=number_of_days)

    prices = fetch_energy_prices(
        start_time,
        end_time,
        region_config.market_location,
        provider=region_config.market_provider,
        sleep_seconds=sleep_seconds,
        **(region_config.provider_options or {}),
    )

    validate_price_data(
        prices,
        expected_timezone=region_config.timezone,
    )

    return prices


def build_expected_index(
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
    timestep_minutes: int = TARGET_INTERVAL_MINUTES,
) -> pd.DatetimeIndex:
    """Build the interval grid for a window without assuming 96 per day."""

    return pd.date_range(
        start=start_time,
        end=end_time,
        freq=f"{timestep_minutes}min",
        inclusive="left",
    )


## Compatibility wrappers -------------------------------------------------


def get_caiso_real_time_prices(
    date: str,
    location: str,
) -> pd.DataFrame:
    """Raw single-day CAISO LMPs, straight from gridstatus."""

    caiso = gridstatus.CAISO()

    data = caiso.get_lmp(
        date=date,
        market="REAL_TIME_15_MIN",
        locations=[location],
    )

    return data


def get_caiso_real_time_prices_range(
    start_date: str,
    number_of_days: int,
    location: str,
    sleep_seconds: float = 1.0,
) -> pd.DataFrame:
    """Normalized multi-day CAISO prices.

    Preserved for existing callers; new code should prefer
    :func:`fetch_region_prices` or :func:`fetch_energy_prices`.
    """

    start_time = pd.Timestamp(
        start_date,
        tz=LOCAL_TIMEZONE,
    )

    # DateOffset advances local calendar days; Timedelta would add exactly
    # 24 hours and drift by an hour across a daylight-saving transition.
    end_time = start_time + pd.DateOffset(days=number_of_days)

    price_data = fetch_energy_prices(
        start_time,
        end_time,
        location,
        provider="caiso",
        sleep_seconds=sleep_seconds,
    )

    validate_price_data(price_data)

    return price_data


def caiso_price_to_dataframe(
    raw_data: pd.DataFrame,
) -> pd.DataFrame:
    """Normalize a raw CAISO LMP frame to the common price schema."""

    return normalize_price_frame(
        raw_data,
        provider_name="CAISO",
        timestamp_column="Interval Start",
        price_column="LMP",
        timezone=LOCAL_TIMEZONE,
    )


def validate_price_data(
    data: pd.DataFrame,
    expected_rows: int | None = None,
    timestep_minutes: int = TARGET_INTERVAL_MINUTES,
    expected_timezone: str = LOCAL_TIMEZONE,
) -> None:
    """Validate the normalized price schema.

    ``expected_rows`` is honoured when supplied, but callers should leave it
    unset: interval continuity is checked directly, which stays correct
    across daylight-saving transitions where a local day is not 96 intervals.
    """

    required_columns = {
        "timestamp",
        "price_per_kWh",
    }

    missing_columns = required_columns - set(data.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    if data.empty:
        raise ValueError("Price data is empty.")

    if expected_rows is not None and len(data) != expected_rows:
        raise ValueError(
            f"Expected {expected_rows} rows, "
            f"but received {len(data)}."
        )

    if data.isna().any().any():
        raise ValueError("Price data contains missing values.")

    timezone = data["timestamp"].dt.tz

    if timezone is None:
        raise ValueError("Timestamps are not timezone-aware.")

    if str(timezone) != expected_timezone:
        raise ValueError(
            f"Expected timezone {expected_timezone}, "
            f"but received {timezone}."
        )

    try:
        check_intervals(
            data,
            provider_name="Price",
            interval_minutes=timestep_minutes,
        )
    except (
        DuplicateIntervalError,
        MissingIntervalError,
        TimezoneNormalizationError,
    ) as error:
        raise ValueError(str(error)) from error
