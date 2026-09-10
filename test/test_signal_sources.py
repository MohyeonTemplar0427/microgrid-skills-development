"""Source-mode, region-override and price-source tests.

Nothing here contacts a live API.
"""

import pandas as pd
import pytest

from src.signal_pipeline.horizon import build_horizon
from src.signal_pipeline.price_sources import (
    ALL_DAYS,
    WEEKDAYS,
    WEEKEND,
    CSVPrice,
    FixedRetailPrice,
    PriceScheduleError,
    PriceSourceError,
    TimeOfUsePeriod,
    TimeOfUseSchedule,
    UnsupportedPriceModeError,
    WholesaleMarketPrice,
    build_price_source,
)
from src.signal_pipeline.providers import UnsupportedProviderError
from src.signal_pipeline.region_config import (
    REGION_REGISTRY,
    get_region_config,
)
from src.signal_pipeline.signal_loader import (
    SignalLoaderError,
    load_signal_data,
)
from src.signal_pipeline.source_config import (
    INTEGRATED_CSV,
    LIVE_API,
    SourceConfigurationError,
    TimezoneRequiredError,
    UnknownSourceModeError,
    infer_timezone_from_data,
    resolve_integrated_csv_config,
    resolve_live_api_config,
    resolve_signal_config,
)

PACIFIC = "America/Los_Angeles"
EASTERN = "America/New_York"


## Requirement 1: conditional data-source behaviour -----------------------


def test_live_api_requires_a_region():
    with pytest.raises(SourceConfigurationError) as error:
        resolve_signal_config(LIVE_API, region=None)

    assert "requires a region" in str(error.value)


def test_live_api_rejects_an_empty_region():
    with pytest.raises(SourceConfigurationError):
        resolve_signal_config(LIVE_API, region="   ")


def test_live_api_resolves_every_identifier_from_the_region():
    config = resolve_signal_config(LIVE_API, region="pjm_western_hub")

    assert config.source_mode == LIVE_API
    assert config.region == "pjm_western_hub"
    assert config.market_provider == "pjm"
    assert config.market_location == "51288"
    assert config.carbon_provider == "electricity_maps"
    assert config.carbon_zone == "US-MIDA-PJM"
    assert config.timezone == EASTERN
    assert config.timezone_source == "region_preset"
    assert config.requires_market_api is True


def test_csv_mode_does_not_require_a_region():
    config = resolve_signal_config(INTEGRATED_CSV, timezone=PACIFIC)

    assert config.source_mode == INTEGRATED_CSV
    assert config.region is None
    assert config.requires_market_api is False


def test_csv_mode_uses_no_market_or_carbon_identifiers():
    config = resolve_signal_config(INTEGRATED_CSV, timezone=PACIFIC)

    assert config.market_provider is None
    assert config.market_location is None
    assert config.carbon_provider is None
    assert config.carbon_zone is None


def test_csv_mode_rejects_market_identifiers_that_would_be_ignored():
    with pytest.raises(SourceConfigurationError) as error:
        resolve_signal_config(
            INTEGRATED_CSV,
            timezone=PACIFIC,
            market_provider="pjm",
        )

    assert "does not use market" in str(error.value)


def test_unknown_source_mode_is_rejected():
    with pytest.raises(UnknownSourceModeError):
        resolve_signal_config("parquet_dump", timezone=PACIFIC)


## CSV timezone requirements ----------------------------------------------


def test_csv_mode_accepts_an_explicit_named_timezone():
    config = resolve_integrated_csv_config(timezone=EASTERN)

    assert config.timezone == EASTERN
    assert config.timezone_source == "explicit"


def test_csv_mode_reads_a_named_timezone_from_the_data():
    data = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                pd.Timestamp("2026-08-25", tz=PACIFIC),
                periods=4,
                freq="15min",
            )
        }
    )

    config = resolve_integrated_csv_config(data=data)

    assert config.timezone == PACIFIC
    assert config.timezone_source == "input_metadata"


def test_csv_mode_refuses_to_guess_when_no_timezone_is_available():
    naive = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-08-25", periods=4, freq="15min"
            )
        }
    )

    with pytest.raises(TimezoneRequiredError) as error:
        resolve_integrated_csv_config(data=naive)

    assert "named timezone" in str(error.value)


@pytest.mark.parametrize("zone", ["Etc/GMT+8", "UTC-08:00"])
def test_csv_mode_refuses_a_fixed_offset(zone):
    """A fixed offset cannot express daylight-saving transitions."""

    offset_data = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-08-25", periods=4, freq="15min", tz="UTC"
            ).tz_convert(zone)
        }
    )

    assert infer_timezone_from_data(offset_data) is None

    with pytest.raises(TimezoneRequiredError):
        resolve_integrated_csv_config(data=offset_data)


def test_csv_mode_accepts_utc_as_a_real_timezone():
    utc_data = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-08-25", periods=4, freq="15min", tz="UTC"
            )
        }
    )

    assert infer_timezone_from_data(utc_data) == "UTC"


def test_csv_mode_with_no_data_and_no_timezone_is_rejected():
    with pytest.raises(TimezoneRequiredError):
        resolve_integrated_csv_config()


def test_unknown_timezone_is_rejected():
    with pytest.raises(Exception):
        resolve_integrated_csv_config(timezone="Mars/Olympus_Mons")


## Requirement 2: region defaults with overrides --------------------------


def test_region_override_replaces_only_the_named_field():
    config = resolve_live_api_config(
        "caiso_np15",
        market_location="TH_SP15_GEN-APND",
    )

    assert config.market_location == "TH_SP15_GEN-APND"
    # Everything else still comes from the preset.
    assert config.market_provider == "caiso"
    assert config.carbon_zone == "US-CAL-CISO"
    assert config.timezone == PACIFIC


def test_every_region_field_can_be_overridden():
    config = resolve_live_api_config(
        "caiso_np15",
        market_provider="ercot",
        market_location="HB_HOUSTON",
        carbon_provider="electricity_maps",
        carbon_zone="US-TEX-ERCO",
        timezone="America/Chicago",
    )

    assert config.market_provider == "ercot"
    assert config.market_location == "HB_HOUSTON"
    assert config.carbon_zone == "US-TEX-ERCO"
    assert config.timezone == "America/Chicago"
    assert config.timezone_source == "override"


def test_overrides_are_validated():
    with pytest.raises(UnsupportedProviderError):
        resolve_live_api_config("caiso_np15", market_provider="miso")

    with pytest.raises(SourceConfigurationError):
        resolve_live_api_config("caiso_np15", market_location="  ")

    with pytest.raises(SourceConfigurationError):
        resolve_live_api_config("caiso_np15", carbon_provider="watttime")


def test_global_region_presets_are_never_mutated():
    """Resolution must return a new object, not edit the registry."""

    before = get_region_config("caiso_np15")
    snapshot = (
        before.market_provider,
        before.market_location,
        before.carbon_zone,
        before.timezone,
    )

    resolve_live_api_config(
        "caiso_np15",
        market_provider="ercot",
        market_location="HB_HOUSTON",
        carbon_zone="US-TEX-ERCO",
        timezone="America/Chicago",
    )

    after = get_region_config("caiso_np15")

    assert (
        after.market_provider,
        after.market_location,
        after.carbon_zone,
        after.timezone,
    ) == snapshot

    assert REGION_REGISTRY["caiso_np15"].market_location == (
        "TH_NP15_GEN-APND"
    )


def test_resolved_config_is_independent_of_the_registry_object():
    preset = get_region_config("pjm_western_hub")
    resolved = resolve_live_api_config("pjm_western_hub")

    assert resolved.market_location == preset.market_location
    assert resolved is not preset


## Requirement 3: price sources -------------------------------------------


def make_horizon(days: int = 1, timezone: str = PACIFIC):
    return build_horizon("2026-08-25", days, timezone)


class FakeCAISOClient:
    def __init__(self, frame):
        self.frame = frame

    def get_lmp(self, **kwargs):
        return self.frame


def test_wholesale_prices_are_normalized_from_mwh(monkeypatch):
    horizon = make_horizon()

    raw = pd.DataFrame(
        {
            "Interval Start": horizon.index,
            "LMP": 50.0,
        }
    )

    monkeypatch.setattr(
        "gridstatus.CAISO", lambda: FakeCAISOClient(raw)
    )

    source = WholesaleMarketPrice(
        market_provider="caiso",
        market_location="TH_NP15_GEN-APND",
    )

    prices = source.build_prices(horizon)

    assert list(prices.columns) == ["timestamp", "price_per_kWh"]
    assert len(prices) == horizon.interval_count
    # $50/MWh is $0.05/kWh.
    assert prices["price_per_kWh"].eq(0.05).all()


def test_fixed_retail_price_fills_every_interval():
    horizon = make_horizon()

    prices = FixedRetailPrice(price_per_kWh=0.23).build_prices(horizon)

    assert len(prices) == horizon.interval_count
    assert prices["price_per_kWh"].eq(0.23).all()
    assert prices["timestamp"].iloc[0] == horizon.start


def test_fixed_retail_price_fills_a_dst_day_correctly():
    horizon = build_horizon("2026-03-08", 1, EASTERN)

    prices = FixedRetailPrice(price_per_kWh=0.10).build_prices(horizon)

    assert len(prices) == 92


def test_fixed_retail_rejects_negative_and_non_finite_prices():
    with pytest.raises(PriceSourceError):
        FixedRetailPrice(price_per_kWh=-0.1)

    with pytest.raises(PriceSourceError):
        FixedRetailPrice(price_per_kWh=float("nan"))

    with pytest.raises(PriceSourceError):
        FixedRetailPrice(price_per_kWh="cheap")


## Time-of-use ------------------------------------------------------------


def build_tou_schedule() -> TimeOfUseSchedule:
    return TimeOfUseSchedule(
        periods=(
            TimeOfUsePeriod(
                name="peak",
                price_per_kWh=0.40,
                start_hour=16,
                end_hour=21,
                days=WEEKDAYS,
            ),
            TimeOfUsePeriod(
                name="off_peak",
                price_per_kWh=0.12,
                start_hour=0,
                end_hour=24,
                days=ALL_DAYS,
            ),
        )
    )


def test_time_of_use_prices_change_with_local_hour():
    horizon = make_horizon()

    prices = build_tou_schedule().build_prices(horizon)

    indexed = prices.set_index("timestamp")["price_per_kWh"]

    # 2026-08-25 is a Tuesday.
    peak = pd.Timestamp("2026-08-25 17:00", tz=PACIFIC)
    off_peak = pd.Timestamp("2026-08-25 03:00", tz=PACIFIC)

    assert indexed[peak] == 0.40
    assert indexed[off_peak] == 0.12


def test_time_of_use_treats_weekends_differently():
    horizon = build_horizon("2026-08-29", 1, PACIFIC)  # a Saturday

    prices = build_tou_schedule().build_prices(horizon)

    # The peak period is weekdays only, so Saturday is entirely off-peak.
    assert prices["price_per_kWh"].eq(0.12).all()


def test_time_of_use_period_can_wrap_past_midnight():
    schedule = TimeOfUseSchedule(
        periods=(
            TimeOfUsePeriod(
                name="overnight",
                price_per_kWh=0.05,
                start_hour=22,
                end_hour=6,
            ),
            TimeOfUsePeriod(
                name="daytime",
                price_per_kWh=0.30,
                start_hour=6,
                end_hour=22,
            ),
        )
    )

    horizon = make_horizon()
    indexed = (
        schedule.build_prices(horizon)
        .set_index("timestamp")["price_per_kWh"]
    )

    assert indexed[pd.Timestamp("2026-08-25 23:00", tz=PACIFIC)] == 0.05
    assert indexed[pd.Timestamp("2026-08-25 02:00", tz=PACIFIC)] == 0.05
    assert indexed[pd.Timestamp("2026-08-25 12:00", tz=PACIFIC)] == 0.30


def test_time_of_use_follows_local_wall_clock_across_dst():
    """A 4pm peak stays at 4pm local on a spring-forward day."""

    horizon = build_horizon("2026-03-08", 1, EASTERN)

    prices = build_tou_schedule().build_prices(horizon)
    indexed = prices.set_index("timestamp")["price_per_kWh"]

    assert len(prices) == 92
    assert indexed[pd.Timestamp("2026-03-08 17:00", tz=EASTERN)] == 0.12

    # 8 March 2026 is a Sunday, so use the following weekday for peak.
    weekday_horizon = build_horizon("2026-03-09", 1, EASTERN)
    weekday_prices = (
        build_tou_schedule()
        .build_prices(weekday_horizon)
        .set_index("timestamp")["price_per_kWh"]
    )

    assert weekday_prices[
        pd.Timestamp("2026-03-09 17:00", tz=EASTERN)
    ] == 0.40


def test_time_of_use_rejects_an_uncovered_interval():
    schedule = TimeOfUseSchedule(
        periods=(
            TimeOfUsePeriod(
                name="peak",
                price_per_kWh=0.40,
                start_hour=16,
                end_hour=21,
            ),
        )
    )

    with pytest.raises(PriceScheduleError) as error:
        schedule.build_prices(make_horizon())

    assert "does not cover" in str(error.value)


def test_time_of_use_default_price_fills_uncovered_intervals():
    schedule = TimeOfUseSchedule(
        periods=(
            TimeOfUsePeriod(
                name="peak",
                price_per_kWh=0.40,
                start_hour=16,
                end_hour=21,
            ),
        ),
        default_price_per_kWh=0.15,
    )

    prices = schedule.build_prices(make_horizon())

    assert set(prices["price_per_kWh"].unique()) == {0.40, 0.15}


def test_time_of_use_schedule_validation():
    with pytest.raises(PriceScheduleError):
        TimeOfUseSchedule(periods=())

    with pytest.raises(PriceScheduleError):
        TimeOfUsePeriod(
            name="bad", price_per_kWh=0.1, start_hour=5, end_hour=5
        )

    with pytest.raises(PriceScheduleError):
        TimeOfUsePeriod(
            name="bad", price_per_kWh=0.1, start_hour=-1, end_hour=5
        )

    with pytest.raises(PriceScheduleError):
        TimeOfUsePeriod(
            name="bad",
            price_per_kWh=0.1,
            start_hour=0,
            end_hour=5,
            days=frozenset({9}),
        )

    with pytest.raises(PriceSourceError):
        TimeOfUsePeriod(
            name="bad", price_per_kWh=-1.0, start_hour=0, end_hour=5
        )


def test_duplicate_time_of_use_period_names_are_rejected():
    with pytest.raises(PriceScheduleError):
        TimeOfUseSchedule(
            periods=(
                TimeOfUsePeriod(
                    name="peak", price_per_kWh=0.4, start_hour=0, end_hour=5
                ),
                TimeOfUsePeriod(
                    name="peak", price_per_kWh=0.2, start_hour=5, end_hour=9
                ),
            )
        )


def test_weekend_constant_covers_saturday_and_sunday():
    assert WEEKEND == frozenset({5, 6})
    assert WEEKDAYS | WEEKEND == ALL_DAYS


## CSV prices -------------------------------------------------------------


def test_csv_price_reads_a_configured_column():
    horizon = make_horizon()

    data = pd.DataFrame(
        {
            "timestamp": horizon.index,
            "tariff": 0.18,
        }
    )

    prices = CSVPrice(
        data=data, price_column="tariff"
    ).build_prices(horizon)

    assert prices["price_per_kWh"].eq(0.18).all()


def test_csv_price_converts_declared_mwh_units():
    horizon = make_horizon()

    data = pd.DataFrame(
        {"timestamp": horizon.index, "price_per_kWh": 40.0}
    )

    prices = CSVPrice(
        data=data, source_unit="$/MWh"
    ).build_prices(horizon)

    assert prices["price_per_kWh"].eq(0.04).all()


def test_csv_price_rejects_an_unknown_unit():
    horizon = make_horizon()
    data = pd.DataFrame(
        {"timestamp": horizon.index, "price_per_kWh": 1.0}
    )

    with pytest.raises(PriceSourceError):
        CSVPrice(data=data, source_unit="cents/kWh").build_prices(horizon)


def test_csv_price_rejects_nonnumeric_and_missing_columns():
    horizon = make_horizon()

    nonnumeric = pd.DataFrame(
        {"timestamp": horizon.index, "price_per_kWh": "free"}
    )

    with pytest.raises(PriceSourceError):
        CSVPrice(data=nonnumeric).build_prices(horizon)

    wrong_column = pd.DataFrame(
        {"timestamp": horizon.index, "rate": 0.1}
    )

    with pytest.raises(PriceSourceError) as error:
        CSVPrice(data=wrong_column).build_prices(horizon)

    assert "price_per_kWh" in str(error.value)


def test_csv_price_detects_incomplete_coverage():
    horizon = make_horizon()

    data = pd.DataFrame(
        {"timestamp": horizon.index[:-5], "price_per_kWh": 0.1}
    )

    with pytest.raises(Exception):
        CSVPrice(data=data).build_prices(horizon)


def test_price_source_factory_and_unknown_mode():
    source = build_price_source("fixed_retail", price_per_kWh=0.2)

    assert isinstance(source, FixedRetailPrice)

    with pytest.raises(UnsupportedPriceModeError):
        build_price_source("negotiated", price_per_kWh=0.2)


## The stable loader entry point ------------------------------------------


def make_integrated_frame(horizon) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": horizon.index,
            "load_kw": 10.0,
            "pv_kw": 2.0,
            "net_load_kw": 8.0,
            "price_per_kWh": 0.05,
            "gCO2/kWh": 250.0,
        }
    )


def test_loader_returns_the_integrated_schema_from_csv():
    horizon = make_horizon()
    config = resolve_integrated_csv_config(timezone=PACIFIC)

    data = load_signal_data(
        config,
        horizon,
        integrated_data=make_integrated_frame(horizon),
    )

    assert list(data.columns) == [
        "timestamp",
        "load_kw",
        "pv_kw",
        "net_load_kw",
        "price_per_kWh",
        "gCO2/kWh",
    ]
    assert len(data) == horizon.interval_count


def test_loader_rejects_a_timezone_mismatch():
    horizon = make_horizon()
    config = resolve_integrated_csv_config(timezone=EASTERN)

    with pytest.raises(SourceConfigurationError):
        load_signal_data(
            config,
            horizon,
            integrated_data=make_integrated_frame(horizon),
        )


def test_loader_rejects_integrated_data_missing_columns():
    horizon = make_horizon()
    config = resolve_integrated_csv_config(timezone=PACIFIC)

    incomplete = make_integrated_frame(horizon).drop(columns=["pv_kw"])

    with pytest.raises(SignalLoaderError) as error:
        load_signal_data(config, horizon, integrated_data=incomplete)

    assert "pv_kw" in str(error.value)


def test_live_api_loader_requires_a_site_profile():
    """Market APIs price a node; they never supply site load or PV."""

    horizon = make_horizon()
    config = resolve_live_api_config("caiso_np15")

    with pytest.raises(SignalLoaderError) as error:
        load_signal_data(config, horizon, site_profile=None)

    assert "site_profile" in str(error.value)


def test_live_api_loader_joins_site_profile_with_market_signals(monkeypatch):
    horizon = make_horizon()
    config = resolve_live_api_config("caiso_np15")

    site_profile = pd.DataFrame(
        {
            "timestamp": horizon.index,
            "load_kw": 10.0,
            "pv_kw": 2.0,
        }
    )

    carbon = pd.DataFrame(
        {"timestamp": horizon.index, "gCO2/kWh": 300.0}
    )

    monkeypatch.setattr(
        "src.signal_pipeline.signal_loader.emd.get_multi_day_carbon_data",
        lambda *args, **kwargs: carbon,
    )

    data = load_signal_data(
        config,
        horizon,
        site_profile=site_profile,
        price_source=FixedRetailPrice(price_per_kWh=0.2),
        carbon_api_key="test-key",
    )

    assert len(data) == horizon.interval_count
    assert data["net_load_kw"].eq(8.0).all()
    assert data["price_per_kWh"].eq(0.2).all()
    assert data["gCO2/kWh"].eq(300.0).all()
