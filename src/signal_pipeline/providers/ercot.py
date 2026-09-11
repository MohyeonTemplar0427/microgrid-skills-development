"""ERCOT adapter.

Source market: REAL_TIME_15_MIN **Settlement Point Prices** in $/MWh. ERCOT
is already on the pipeline's 15-minute grid, so no resampling is needed.

Two things differ from the other adapters:

* ERCOT prices settlement points, not LMP nodes. The gridstatus call is
  ``get_spp`` (not ``get_lmp``) and the price column is ``SPP`` (not ``LMP``).
* Locations are settlement point *names* -- ``HB_HOUSTON`` is the Houston
  trading hub. Load zones (``LZ_HOUSTON``) and resource nodes use the same
  argument.

No credentials are required; gridstatus reads ERCOT's public MIS reports.
"""

import os

import certifi
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

HOUSTON_HUB_SETTLEMENT_POINT = "HB_HOUSTON"


class ERCOTProvider(MarketProvider):
    name = "ERCOT"
    default_timezone = "America/Chicago"
    source_price_unit = "$/MWh"
    native_interval_minutes = 15
    # gridstatus declares no date-range frequency for ERCOT SPP, so the whole
    # window goes through in one call, as it does for CAISO.
    max_chunk_days = None
    requires_credentials = False

    def __init__(self, location_type: str = "ALL") -> None:
        self.location_type = location_type

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
                "ERCOT requires a settlement point name such as "
                f"{HOUSTON_HUB_SETTLEMENT_POINT}."
            )

        if str(location).isdigit():
            raise InvalidLocationError(
                f"ERCOT locations are settlement point names, not numeric "
                f"ids; received {location!r}. The Houston trading hub is "
                f"{HOUSTON_HUB_SETTLEMENT_POINT}."
            )

        client = gridstatus.Ercot()
        os.environ.setdefault(
            "SSL_CERT_FILE",
            certifi.where(),
        )

        try:
            raw_data = client.get_spp(
                date=start,
                end=end,
                market=gridstatus.Markets.REAL_TIME_15_MIN,
                locations=[location],
                location_type=self.location_type,
            )
        except gridstatus.NoDataFoundException as error:
            raise EmptyResponseError(
                f"ERCOT returned no data for settlement point {location} "
                f"between {start} and {end}."
            ) from error
        except SignalProviderError:
            raise
        except Exception as error:
            raise SignalProviderError(
                f"ERCOT price retrieval failed for settlement point "
                f"{location}: {error}"
            ) from error

        prices = normalize_price_frame(
            raw_data,
            provider_name=self.name,
            timestamp_column="Interval Start",
            price_column="SPP",
            timezone=self.default_timezone,
        )

        prices = trim_to_window(prices, start, end)

        if prices.empty:
            raise EmptyResponseError(
                f"ERCOT returned no intervals inside {start} to {end} "
                f"for settlement point {location}."
            )

        check_intervals(
            prices,
            provider_name=self.name,
        )

        return prices
