"""Data-source configuration for the guided analysis workflow.

Two source modes are supported:

``live_api``
    Prices and carbon intensity are fetched from provider APIs. A region is
    required and resolves through the region registry.

``integrated_csv``
    Every signal arrives in one file the user already has. No region, market
    provider, market location or carbon zone is involved -- but a **named**
    timezone is still required, either supplied by the user or read from
    reliable metadata in the file.

A region preset supplies *defaults*. Overrides are applied on top and the
result is validated. Registry entries are never mutated: resolution always
returns a new object.
"""

from dataclasses import dataclass, replace

import pandas as pd

from .providers import (
    UnsupportedProviderError,
    supported_providers,
)
from .providers.base import (
    SignalProviderError,
    TimezoneNormalizationError,
)
from .region_config import RegionConfig, get_region_config, supported_regions

LIVE_API = "live_api"
INTEGRATED_CSV = "integrated_csv"

SOURCE_MODES = (LIVE_API, INTEGRATED_CSV)

SUPPORTED_CARBON_PROVIDERS = frozenset({"electricity_maps"})


class SourceConfigurationError(SignalProviderError):
    pass


class UnknownSourceModeError(SourceConfigurationError):
    pass


class TimezoneRequiredError(SourceConfigurationError):
    pass


@dataclass(frozen=True)
class ResolvedSignalConfig:
    """A validated, fully-resolved signal source configuration.

    For ``integrated_csv`` every market and carbon identifier is ``None``:
    nothing is fetched, so nothing needs identifying.
    """

    source_mode: str
    timezone: str

    region: str | None = None
    market_provider: str | None = None
    market_location: str | None = None
    carbon_provider: str | None = None
    carbon_zone: str | None = None

    timezone_source: str = "explicit"

    @property
    def requires_market_api(self) -> bool:
        return self.source_mode == LIVE_API


def resolve_live_api_config(
    region: str,
    *,
    market_provider: str | None = None,
    market_location: str | None = None,
    carbon_provider: str | None = None,
    carbon_zone: str | None = None,
    timezone: str | None = None,
) -> ResolvedSignalConfig:
    """Resolve a region preset, then apply and validate overrides.

    The registry entry is copied, never mutated, so a later call for the same
    region still sees the original preset.
    """

    if region is None or not str(region).strip():
        raise SourceConfigurationError(
            f"Source mode {LIVE_API!r} requires a region. "
            f"Known regions: {supported_regions()}."
        )

    preset = get_region_config(region)

    overrides = {
        "market_provider": market_provider,
        "market_location": market_location,
        "carbon_provider": carbon_provider,
        "carbon_zone": carbon_zone,
        "timezone": timezone,
    }

    applied = {
        field: value
        for field, value in overrides.items()
        if value is not None
    }

    resolved: RegionConfig = replace(preset, **applied)

    _validate_resolved_region(resolved)

    return ResolvedSignalConfig(
        source_mode=LIVE_API,
        timezone=resolved.timezone,
        region=resolved.region,
        market_provider=resolved.market_provider,
        market_location=resolved.market_location,
        carbon_provider=resolved.carbon_provider,
        carbon_zone=resolved.carbon_zone,
        timezone_source="override" if timezone else "region_preset",
    )


def _validate_resolved_region(resolved: RegionConfig) -> None:
    if resolved.market_provider not in supported_providers():
        raise UnsupportedProviderError(
            f"Unsupported market provider "
            f"{resolved.market_provider!r}. "
            f"Supported providers: {supported_providers()}."
        )

    if not str(resolved.market_location).strip():
        raise SourceConfigurationError(
            "Market location must not be empty."
        )

    if resolved.carbon_provider not in SUPPORTED_CARBON_PROVIDERS:
        raise SourceConfigurationError(
            f"Unsupported carbon provider "
            f"{resolved.carbon_provider!r}. Supported carbon providers: "
            f"{sorted(SUPPORTED_CARBON_PROVIDERS)}."
        )

    if not str(resolved.carbon_zone).strip():
        raise SourceConfigurationError(
            "Carbon zone must not be empty."
        )

    _require_named_timezone(resolved.timezone)


def resolve_integrated_csv_config(
    *,
    timezone: str | None = None,
    data: pd.DataFrame | None = None,
) -> ResolvedSignalConfig:
    """Resolve a CSV source. No region, provider, node or carbon zone.

    The timezone comes from the user, or from a tz-aware timestamp column
    carrying a **named** zone. A fixed UTC offset is not enough: it cannot
    say when daylight-saving transitions occur, so it is refused rather than
    guessed at.
    """

    if timezone:
        _require_named_timezone(timezone)

        return ResolvedSignalConfig(
            source_mode=INTEGRATED_CSV,
            timezone=timezone,
            timezone_source="explicit",
        )

    inferred = (
        infer_timezone_from_data(data)
        if data is not None
        else None
    )

    if inferred is None:
        raise TimezoneRequiredError(
            "Integrated CSV mode needs a timezone. Supply a named timezone "
            "such as 'America/Los_Angeles', or provide data whose timestamp "
            "column is localized to a named zone. A fixed UTC offset is not "
            "sufficient because it does not define daylight-saving "
            "transitions."
        )

    return ResolvedSignalConfig(
        source_mode=INTEGRATED_CSV,
        timezone=inferred,
        timezone_source="input_metadata",
    )


def infer_timezone_from_data(
    data: pd.DataFrame | None,
) -> str | None:
    """Return the named timezone of a timestamp column, if it has one."""

    if data is None or "timestamp" not in data.columns:
        return None

    timestamps = data["timestamp"]

    if not pd.api.types.is_datetime64_any_dtype(timestamps):
        return None

    zone = timestamps.dt.tz

    if zone is None:
        return None

    name = str(zone)

    # UTC is a real analysis timezone and genuinely has no transitions.
    if name == "UTC":
        return "UTC"

    # A bare fixed offset renders as 'UTC+05:00' or 'pytz.FixedOffset(-480)'
    # and carries no DST rules. Neither do the Etc/GMT±N zones, despite
    # looking like ordinary IANA region names.
    if "/" not in name or name.startswith("Etc/"):
        return None

    return name


def _require_named_timezone(timezone: str) -> None:
    if not timezone or not str(timezone).strip():
        raise TimezoneRequiredError("Timezone must not be empty.")

    try:
        pd.Timestamp("2026-01-01", tz=timezone)
    except Exception as error:
        raise TimezoneNormalizationError(
            f"Unknown timezone {timezone!r}."
        ) from error


def resolve_signal_config(
    source_mode: str,
    *,
    region: str | None = None,
    timezone: str | None = None,
    data: pd.DataFrame | None = None,
    **overrides,
) -> ResolvedSignalConfig:
    """Resolve any supported source mode into a validated configuration."""

    mode = str(source_mode).strip().lower()

    if mode == LIVE_API:
        return resolve_live_api_config(
            region,
            timezone=timezone,
            **overrides,
        )

    if mode == INTEGRATED_CSV:
        rejected = {
            name: value
            for name, value in overrides.items()
            if value is not None
        }

        if rejected:
            raise SourceConfigurationError(
                f"Source mode {INTEGRATED_CSV!r} does not use market or "
                f"carbon identifiers, but received: {sorted(rejected)}."
            )

        return resolve_integrated_csv_config(
            timezone=timezone,
            data=data,
        )

    raise UnknownSourceModeError(
        f"Unknown source mode {source_mode!r}. "
        f"Supported modes: {list(SOURCE_MODES)}."
    )
