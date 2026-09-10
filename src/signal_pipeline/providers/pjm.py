"""PJM adapter.

Source market: REAL_TIME_5_MIN LMPs in $/MWh. PJM publishes **no 15-minute
market**, so this adapter fetches 5-minute data and averages each group of
three into the pipeline's 15-minute grid.

Locations are numeric **pnode ids**, not names -- Western Hub is ``51288``.
Use ``gridstatus.PJM().get_pnode_ids()`` to look others up.

Requires ``PJM_API_KEY``. PJM keeps only ~186 days of 5-minute real-time data
online, so older windows are rejected up front rather than returning empty.
"""

import os

import gridstatus
import pandas as pd

from .base import (
    EmptyResponseError,
    InvalidLocationError,
    MarketProvider,
    MissingCredentialsError,
    RangeLimitError,
    SignalProviderError,
    check_intervals,
    combine_chunks,
    iterate_chunks,
    normalize_price_frame,
    require_aware_timestamps,
    resample_to_target_interval,
    trim_to_window,
)

PJM_API_KEY_ENV_VAR = "PJM_API_KEY"

WESTERN_HUB_PNODE_ID = "51288"


class PJMProvider(MarketProvider):
    name = "PJM"
    default_timezone = "America/New_York"
    source_price_unit = "$/MWh"
    native_interval_minutes = 5
    # 5-min data for one pnode is 288 rows/day; 30 days stays well inside
    # PJM's 50,000-row page and keeps a failed chunk cheap to retry.
    max_chunk_days = 30
    archive_limit_days = 186
    requires_credentials = True
    credential_env_var = PJM_API_KEY_ENV_VAR

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv(PJM_API_KEY_ENV_VAR)

    def _build_client(self) -> "gridstatus.PJM":
        if not self.api_key:
            raise MissingCredentialsError(
                f"PJM requires an API key. Set {PJM_API_KEY_ENV_VAR} in your "
                f"environment or .env file. Register at "
                f"https://dataminer2.pjm.com/ to obtain one."
            )

        return gridstatus.PJM(api_key=self.api_key)

    def _check_archive_window(self, start: pd.Timestamp) -> None:
        oldest_available = (
            pd.Timestamp.now(tz=self.default_timezone)
            - pd.Timedelta(days=self.archive_limit_days)
        )

        if start < oldest_available:
            raise RangeLimitError(
                f"PJM keeps only {self.archive_limit_days} days of "
                f"5-minute real-time LMPs. Requested start {start} is older "
                f"than {oldest_available.date()}."
            )

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
                "PJM requires a numeric pnode id, for example "
                f"{WESTERN_HUB_PNODE_ID} for Western Hub."
            )

        if not str(location).isdigit():
            raise InvalidLocationError(
                f"PJM locations are numeric pnode ids, not names; received "
                f"{location!r}. Western Hub is {WESTERN_HUB_PNODE_ID}. "
                f"Use gridstatus.PJM().get_pnode_ids() to look up others."
            )

        self._check_archive_window(start)

        client = self._build_client()

        chunks = []

        for chunk_start, chunk_end in iterate_chunks(
            start,
            end,
            self.max_chunk_days,
        ):
            chunks.append(
                self._fetch_chunk(
                    client,
                    chunk_start,
                    chunk_end,
                    location,
                )
            )

        combined = combine_chunks(
            chunks,
            provider_name=self.name,
        )

        combined = trim_to_window(combined, start, end)

        if combined.empty:
            raise EmptyResponseError(
                f"PJM returned no intervals inside {start} to {end} "
                f"for pnode {location}."
            )

        prices = resample_to_target_interval(
            combined,
            native_interval_minutes=self.native_interval_minutes,
            provider_name=self.name,
        )

        check_intervals(
            prices,
            provider_name=self.name,
        )

        return prices

    def _fetch_chunk(
        self,
        client: "gridstatus.PJM",
        chunk_start: pd.Timestamp,
        chunk_end: pd.Timestamp,
        location: str,
    ) -> pd.DataFrame:

        try:
            raw_data = client.get_lmp(
                date=chunk_start,
                end=chunk_end,
                market=gridstatus.Markets.REAL_TIME_5_MIN,
                locations=[location],
            )
        except gridstatus.NoDataFoundException as error:
            raise EmptyResponseError(
                f"PJM returned no data for pnode {location} "
                f"between {chunk_start} and {chunk_end}."
            ) from error
        except SignalProviderError:
            raise
        except Exception as error:
            raise SignalProviderError(
                f"PJM price retrieval failed for pnode {location} "
                f"between {chunk_start} and {chunk_end}: {error}"
            ) from error

        return normalize_price_frame(
            raw_data,
            provider_name=self.name,
            timestamp_column="Interval Start",
            price_column="LMP",
            timezone=self.default_timezone,
        )
