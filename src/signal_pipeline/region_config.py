"""User-facing regions mapped to their market and carbon identifiers.

One region name resolves to four separate identifiers plus a timezone. They
are deliberately not interchangeable: a CAISO node name is meaningless to
PJM, and neither ISO's identifier is an Electricity Maps zone.
"""

from dataclasses import dataclass

from .providers import UnknownRegionError, supported_providers


@dataclass(frozen=True)
class RegionConfig:
    """Everything needed to retrieve both signals for one region."""

    region: str
    market_provider: str
    market_location: str
    carbon_provider: str
    carbon_zone: str
    timezone: str
    description: str = ""

    # Construction options for the adapter, for providers that front more
    # than one market and so cannot infer dataset or timezone from the
    # provider name alone. Options an adapter does not accept are dropped.
    provider_options: dict | None = None


REGION_REGISTRY: dict[str, RegionConfig] = {
    "caiso_np15": RegionConfig(
        region="caiso_np15",
        market_provider="caiso",
        market_location="TH_NP15_GEN-APND",
        carbon_provider="electricity_maps",
        carbon_zone="US-CAL-CISO",
        timezone="America/Los_Angeles",
        description="CAISO NP15 generation trading hub, Northern California.",
    ),
    "ercot_houston_hub": RegionConfig(
        region="ercot_houston_hub",
        market_provider="ercot",
        market_location="HB_HOUSTON",
        carbon_provider="electricity_maps",
        carbon_zone="US-TEX-ERCO",
        timezone="America/Chicago",
        description=(
            "ERCOT Houston trading hub (settlement point HB_HOUSTON), Texas. "
            "No credentials required."
        ),
    ),
    "pjm_western_hub": RegionConfig(
        region="pjm_western_hub",
        market_provider="pjm",
        market_location="51288",
        carbon_provider="electricity_maps",
        carbon_zone="US-MIDA-PJM",
        timezone="America/New_York",
        description=(
            "PJM Western Hub (pnode 51288), Mid-Atlantic. "
            "Requires PJM_API_KEY."
        ),
    ),
    "pjm_western_hub_gridstatus": RegionConfig(
        region="pjm_western_hub_gridstatus",
        market_provider="gridstatus_io",
        market_location="WESTERN HUB",
        carbon_provider="electricity_maps",
        carbon_zone="US-MIDA-PJM",
        timezone="America/New_York",
        description=(
            "PJM Western Hub via the GridStatus.io hosted API. Same market "
            "as pjm_western_hub, but reached with a self-serve "
            "GRIDSTATUS_API_KEY instead of PJM's own credential."
        ),
        provider_options={
            "dataset": "pjm_lmp_real_time_5_min",
            "timezone": "America/New_York",
            "native_interval_minutes": 5,
        },
    ),
}


def get_region_config(region: str) -> RegionConfig:
    key = str(region).strip().lower()

    if key not in REGION_REGISTRY:
        raise UnknownRegionError(
            f"Unknown region {region!r}. "
            f"Known regions: {sorted(REGION_REGISTRY)}. "
            f"Supported market providers: {supported_providers()}."
        )

    return REGION_REGISTRY[key]


def supported_regions() -> list[str]:
    return sorted(REGION_REGISTRY)
