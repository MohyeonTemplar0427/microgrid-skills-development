"""CAISO adapter.

Source market: REAL_TIME_15_MIN LMPs in $/MWh, already on the pipeline's
15-minute grid. Locations are node *names* (for example
``TH_NP15_GEN-APND``). No credentials are required.

gridstatus splits CAISO requests internally and honours ``sleep`` between
them, so this adapter passes the whole window through as a single chunk —
matching the behaviour the project has always had.
"""

import gridstatus
import pandas as pd

from .base import (
    EmptyResponseError,
    InvalidLocationError,
    MarketProvider,
    SignalProviderError,
    check_intervals,
    normalize_price_frame,
    require_aware_timestamps,
    trim_to_window,
)


class CAISOProvider(MarketProvider):
    name = "CAISO"
    default_timezone = "America/Los_Angeles"
    source_price_unit = "$/MWh"
    native_interval_minutes = 15
    max_chunk_days = None
    requires_credentials = False

    def __init__(self, sleep_seconds: float = 1.0) -> None:
        self.sleep_seconds = sleep_seconds

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
                "CAISO requires a node name such as TH_NP15_GEN-APND."
            )

        client = gridstatus.CAISO()

        try:
            raw_data = client.get_lmp(
                date=start,
                end=end,
                market=gridstatus.Markets.REAL_TIME_15_MIN,
                locations=[location],
                sleep=self.sleep_seconds,
            )
        except gridstatus.NoDataFoundException as error:
            raise EmptyResponseError(
                f"CAISO returned no data for node {location} "
                f"between {start} and {end}."
            ) from error
        except SignalProviderError:
            raise
        except Exception as error:
            raise SignalProviderError(
                f"CAISO price retrieval failed for node {location}: {error}"
            ) from error

        prices = normalize_price_frame(
            raw_data,
            provider_name=self.name,
            timestamp_column="Interval Start",
            price_column="LMP",
            timezone=self.default_timezone,
        )

        prices = trim_to_window(prices, start, end)

        if prices.empty:
            raise EmptyResponseError(
                f"CAISO returned no intervals inside {start} to {end} "
                f"for node {location}."
            )

        check_intervals(
            prices,
            provider_name=self.name,
        )

        return prices
