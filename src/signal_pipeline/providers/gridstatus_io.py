"""GridStatus.io hosted-API adapter.

Unlike the other adapters, this one is not tied to a single ISO. It fronts
GridStatus.io's hosted API, which republishes data from many ISOs behind one
credential -- useful where an ISO's own API has a heavy onboarding process
(PJM requires a non-member confirmation before issuing a key, whereas a
GridStatus account is self-serve).

Because it spans ISOs, ``default_timezone`` and the interval length are
instance attributes set per region rather than class constants.

Requires ``GRIDSTATUS_API_KEY``. The free tier is row-metered, so the node
filter is applied **server-side**: an unfiltered PJM LMP day is millions of
rows across every pnode, while one filtered node is 288.
"""

import os

import pandas as pd

from .base import (
    EmptyResponseError,
    InvalidLocationError,
    MarketProvider,
    MissingCredentialsError,
    SignalProviderError,
    check_intervals,
    normalize_price_frame,
    require_aware_timestamps,
    resample_to_target_interval,
    trim_to_window,
)

GRIDSTATUS_API_KEY_ENV_VAR = "GRIDSTATUS_API_KEY"


class GridStatusIOProvider(MarketProvider):
    name = "GridStatus.io"
    source_price_unit = "$/MWh"
    max_chunk_days = None
    requires_credentials = True
    credential_env_var = GRIDSTATUS_API_KEY_ENV_VAR

    def __init__(
        self,
        api_key: str | None = None,
        dataset: str = "pjm_lmp",
        timezone: str = "America/New_York",
        native_interval_minutes: int = 5,
        location_column: str = "location",
        price_column: str = "lmp",
        timestamp_column: str = "interval_start_local",
    ) -> None:
        self.api_key = api_key or os.getenv(GRIDSTATUS_API_KEY_ENV_VAR)
        self.dataset = dataset
        self.default_timezone = timezone
        self.native_interval_minutes = native_interval_minutes
        self.location_column = location_column
        self.price_column = price_column
        self.timestamp_column = timestamp_column

    def _build_client(self):
        if not self.api_key:
            raise MissingCredentialsError(
                f"GridStatus.io requires an API key. Set "
                f"{GRIDSTATUS_API_KEY_ENV_VAR} in your environment or .env "
                f"file. Sign up at https://www.gridstatus.io/settings/api."
            )

        try:
            from gridstatusio import GridStatusClient
        except ImportError as error:
            raise SignalProviderError(
                "The gridstatusio package is not installed. "
                "Install it with: pip install gridstatusio"
            ) from error

        return GridStatusClient(api_key=self.api_key)

    def fetch_energy_prices(
        self,
        start_time: pd.Timestamp,
        end_time: pd.Timestamp,
        location: str,
    ) -> pd.DataFrame:

        start, end = require_aware_timestamps(
            start_time,
            end_time,
            self.default_timezone,
        )

        if not location:
            raise InvalidLocationError(
                f"GridStatus.io dataset {self.dataset!r} requires a location "
                f"to filter on."
            )

        client = self._build_client()

        try:
            raw_data = client.get_dataset(
                self.dataset,
                start=start.isoformat(),
                end=end.isoformat(),
                # Server-side filtering keeps the row-metered free tier
                # viable; an unfiltered PJM day spans every pnode.
                filter_column=self.location_column,
                filter_value=str(location),
                tz=self.default_timezone,
                verbose=False,
            )
        except SignalProviderError:
            raise
        except Exception as error:
            raise SignalProviderError(
                f"GridStatus.io retrieval failed for dataset "
                f"{self.dataset!r} at {location}: {error}"
            ) from error

        prices = normalize_price_frame(
            raw_data,
            provider_name=self.name,
            timestamp_column=self.timestamp_column,
            price_column=self.price_column,
            timezone=self.default_timezone,
        )

        prices = trim_to_window(prices, start, end)

        if prices.empty:
            raise EmptyResponseError(
                f"GridStatus.io returned no intervals inside {start} to "
                f"{end} for {location} in dataset {self.dataset!r}."
            )

        prices = resample_to_target_interval(
            prices,
            native_interval_minutes=self.native_interval_minutes,
            provider_name=self.name,
        )

        check_intervals(
            prices,
            provider_name=self.name,
        )

        return prices
