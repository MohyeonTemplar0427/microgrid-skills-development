"""The single backend entry point for loading normalized signal data.

:func:`load_signal_data` accepts a resolved source configuration and a
horizon, and returns the integrated schema the dispatch layer consumes:

    timestamp, load_kw, pv_kw, net_load_kw, price_per_kWh, gCO2/kWh

Load and PV are always **site profile inputs**. A regional market API reports
prices at a pricing node and a carbon API reports grid intensity for a zone;
neither knows anything about one site's consumption or generation, and
neither is ever used as a source for them.
"""

import pandas as pd

from . import electricity_maps_data as emd
from .horizon import AnalysisHorizon, align_to_horizon
from .price_sources import (
    PriceSource,
    WholesaleMarketPrice,
)
from .providers.base import SignalProviderError
from .source_config import (
    INTEGRATED_CSV,
    LIVE_API,
    ResolvedSignalConfig,
    SourceConfigurationError,
)

INTEGRATED_COLUMNS = (
    "timestamp",
    "load_kw",
    "pv_kw",
    "net_load_kw",
    "price_per_kWh",
    "gCO2/kWh",
)

SITE_PROFILE_COLUMNS = (
    "timestamp",
    "load_kw",
    "pv_kw",
)


class SignalLoaderError(SignalProviderError):
    pass


def load_signal_data(
    config: ResolvedSignalConfig,
    horizon: AnalysisHorizon,
    *,
    site_profile: pd.DataFrame | None = None,
    price_source: PriceSource | None = None,
    integrated_data: pd.DataFrame | None = None,
    carbon_api_key: str | None = None,
) -> pd.DataFrame:
    """Return the integrated signal frame for one analysis.

    ``live_api``
        ``site_profile`` supplies load and PV. Prices come from
        ``price_source`` (defaulting to the region's wholesale node) and
        carbon from the configured carbon zone.

    ``integrated_csv``
        ``integrated_data`` supplies every column; nothing is fetched.
    """

    if config.timezone != horizon.timezone:
        raise SourceConfigurationError(
            f"Source timezone {config.timezone!r} does not match horizon "
            f"timezone {horizon.timezone!r}."
        )

    if config.source_mode == INTEGRATED_CSV:
        return _load_from_integrated_data(integrated_data, horizon)

    if config.source_mode == LIVE_API:
        return _load_from_live_api(
            config,
            horizon,
            site_profile=site_profile,
            price_source=price_source,
            carbon_api_key=carbon_api_key,
        )

    raise SourceConfigurationError(
        f"Unsupported source mode {config.source_mode!r}."
    )


def _load_from_integrated_data(
    integrated_data: pd.DataFrame | None,
    horizon: AnalysisHorizon,
) -> pd.DataFrame:

    if integrated_data is None:
        raise SignalLoaderError(
            "Integrated CSV mode requires integrated_data."
        )

    missing = set(INTEGRATED_COLUMNS) - set(integrated_data.columns)

    if missing:
        raise SignalLoaderError(
            f"Integrated data is missing required columns: "
            f"{sorted(missing)}. Required: {list(INTEGRATED_COLUMNS)}."
        )

    aligned = align_to_horizon(
        integrated_data,
        horizon,
        label="Integrated CSV",
    )

    return validate_integrated_signals(
        aligned[list(INTEGRATED_COLUMNS)],
        horizon,
    )


def _load_from_live_api(
    config: ResolvedSignalConfig,
    horizon: AnalysisHorizon,
    *,
    site_profile: pd.DataFrame | None,
    price_source: PriceSource | None,
    carbon_api_key: str | None,
) -> pd.DataFrame:

    if site_profile is None:
        raise SignalLoaderError(
            "Live API mode requires a site_profile carrying load_kw and "
            "pv_kw. Market APIs price a node; they do not report a site's "
            "load or PV production."
        )

    missing = set(SITE_PROFILE_COLUMNS) - set(site_profile.columns)

    if missing:
        raise SignalLoaderError(
            f"Site profile is missing required columns: {sorted(missing)}."
        )

    profile = align_to_horizon(
        site_profile,
        horizon,
        label="Site profile",
    )

    source = price_source or WholesaleMarketPrice(
        market_provider=config.market_provider,
        market_location=config.market_location,
    )

    prices = source.build_prices(horizon)

    carbon = _fetch_carbon(config, horizon, carbon_api_key)

    merged = profile.merge(prices, on="timestamp", how="inner")
    merged = merged.merge(carbon, on="timestamp", how="inner")

    if len(merged) != horizon.interval_count:
        raise SignalLoaderError(
            f"Signals cover {len(merged)} of {horizon.interval_count} "
            f"intervals after joining load, PV, price and carbon."
        )

    if "net_load_kw" not in merged.columns:
        merged["net_load_kw"] = merged["load_kw"] - merged["pv_kw"]

    return validate_integrated_signals(
        merged[list(INTEGRATED_COLUMNS)],
        horizon,
    )


def _fetch_carbon(
    config: ResolvedSignalConfig,
    horizon: AnalysisHorizon,
    carbon_api_key: str | None,
) -> pd.DataFrame:

    if config.carbon_provider != "electricity_maps":
        raise SourceConfigurationError(
            f"Unsupported carbon provider {config.carbon_provider!r}."
        )

    number_of_days = (horizon.end - horizon.start).days or 1

    carbon = emd.get_multi_day_carbon_data(
        carbon_api_key,
        config.carbon_zone,
        horizon.start.strftime("%Y-%m-%d"),
        number_of_days,
        timezone=config.timezone,
    )

    return align_to_horizon(
        carbon[["timestamp", "gCO2/kWh"]],
        horizon,
        label="Carbon",
    )


def validate_integrated_signals(
    data: pd.DataFrame,
    horizon: AnalysisHorizon,
) -> pd.DataFrame:
    """Check the integrated schema against the horizon."""

    missing = set(INTEGRATED_COLUMNS) - set(data.columns)

    if missing:
        raise SignalLoaderError(
            f"Integrated signals are missing columns: {sorted(missing)}."
        )

    if len(data) != horizon.interval_count:
        raise SignalLoaderError(
            f"Integrated signals have {len(data)} rows but the horizon has "
            f"{horizon.interval_count} intervals."
        )

    if data.isna().any().any():
        raise SignalLoaderError(
            "Integrated signals contain missing values."
        )

    if (data["gCO2/kWh"] < 0).any():
        raise SignalLoaderError(
            "Carbon intensity must not be negative."
        )

    return data.reset_index(drop=True)
