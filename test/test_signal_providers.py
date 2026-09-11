"""Focused tests for the provider-neutral signal pipeline.

Every test runs against fabricated frames shaped like real gridstatus
responses. Nothing here contacts a live API.
"""

import os

import pandas as pd
import pytest

from src.signal_pipeline import gridstatus_data as gsd
from src.signal_pipeline.providers import (
    CAISOProvider,
    ERCOTProvider,
    PJMProvider,
    get_provider,
    supported_providers,
)
from src.signal_pipeline.providers import base
from src.signal_pipeline.providers.base import (
    DuplicateIntervalError,
    EmptyResponseError,
    InvalidLocationError,
    MissingCredentialsError,
    MissingIntervalError,
    RangeLimitError,
    SchemaError,
    TimezoneNormalizationError,
    UnitConversionError,
    UnsupportedProviderError,
)
from src.signal_pipeline.region_config import (
    get_region_config,
    supported_regions,
)
from src.signal_pipeline.providers import UnknownRegionError


PACIFIC = "America/Los_Angeles"
EASTERN = "America/New_York"
CENTRAL = "America/Chicago"


def make_caiso_frame(
    start: str = "2026-08-25 00:00",
    periods: int = 8,
    lmp: float = 50.0,
) -> pd.DataFrame:
    """A raw CAISO REAL_TIME_15_MIN response, prices in $/MWh."""

    interval_start = pd.date_range(
        start=pd.Timestamp(start, tz=PACIFIC),
        periods=periods,
        freq="15min",
    )

    return pd.DataFrame(
        {
            "Time": interval_start,
            "Interval Start": interval_start,
            "Interval End": interval_start + pd.Timedelta(minutes=15),
            "Market": "REAL_TIME_15_MIN",
            "Location": "TH_NP15_GEN-APND",
            "Location Type": "Trading Hub",
            "LMP": lmp,
            "Energy": lmp,
            "Congestion": 0.0,
            "Loss": 0.0,
        }
    )


def make_pjm_frame(
    start_utc: str = "2026-08-25 04:00",
    periods: int = 12,
    lmp: float = 30.0,
) -> pd.DataFrame:
    """A raw PJM REAL_TIME_5_MIN response, prices in $/MWh.

    gridstatus hands back Eastern-localized timestamps; the frame is built
    from UTC here so the adapter has a real conversion to perform.
    """

    interval_start = pd.date_range(
        start=pd.Timestamp(start_utc, tz="UTC"),
        periods=periods,
        freq="5min",
    ).tz_convert("US/Eastern")

    return pd.DataFrame(
        {
            "Time": interval_start,
            "Interval Start": interval_start,
            "Interval End": interval_start + pd.Timedelta(minutes=5),
            "Market": "REAL_TIME_5_MIN",
            "Location Id": "51288",
            "Location Name": "WESTERN HUB",
            "Location Short Name": "WESTERN HUB",
            "Location Type": "HUB",
            "LMP": lmp,
            "Energy": lmp,
            "Congestion": 0.0,
            "Loss": 0.0,
        }
    )


def make_ercot_frame(
    start_utc: str = "2026-08-25 05:00",
    periods: int = 8,
    spp: float = 25.0,
) -> pd.DataFrame:
    """A raw ERCOT REAL_TIME_15_MIN settlement point response, $/MWh.

    ERCOT prices settlement points, so the price column is ``SPP`` rather
    than ``LMP`` and the location is a name, not an id.
    """

    interval_start = pd.date_range(
        start=pd.Timestamp(start_utc, tz="UTC"),
        periods=periods,
        freq="15min",
    ).tz_convert("US/Central")

    return pd.DataFrame(
        {
            "Time": interval_start,
            "Interval Start": interval_start,
            "Interval End": interval_start + pd.Timedelta(minutes=15),
            "Location": "HB_HOUSTON",
            "Location Type": "Trading Hub",
            "Market": "REAL_TIME_15_MIN",
            "SPP": spp,
        }
    )


class FakeCAISOClient:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[dict] = []

    def get_lmp(self, **kwargs) -> pd.DataFrame:
        self.calls.append(kwargs)
        return self.frame


class FakeERCOTClient:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[dict] = []

    def get_spp(self, **kwargs) -> pd.DataFrame:
        self.calls.append(kwargs)
        return self.frame


class FakePJMClient:
    """Serves 5-minute rows for whatever window is asked for.

    ``inclusive_end`` reproduces PJM's habit of returning the interval that
    lands exactly on the requested end, which is what creates duplicated
    boundary rows across chunks.
    """

    def __init__(self, lmp: float = 30.0, inclusive_end: bool = True) -> None:
        self.lmp = lmp
        self.inclusive_end = inclusive_end
        self.calls: list[dict] = []

    def get_lmp(self, **kwargs) -> pd.DataFrame:
        self.calls.append(kwargs)

        interval_start = pd.date_range(
            start=kwargs["date"],
            end=kwargs["end"],
            freq="5min",
            inclusive="both" if self.inclusive_end else "left",
        ).tz_convert("US/Eastern")

        return pd.DataFrame(
            {
                "Interval Start": interval_start,
                "Location Id": "51288",
                "LMP": self.lmp,
            }
        )


## 1. Provider selection ---------------------------------------------------


def test_provider_registry_selects_the_requested_adapter():
    assert isinstance(get_provider("caiso"), CAISOProvider)
    assert isinstance(get_provider("ercot"), ERCOTProvider)
    assert isinstance(get_provider("pjm", api_key="test-key"), PJMProvider)


def test_provider_selection_is_case_insensitive():
    assert isinstance(get_provider("CAISO"), CAISOProvider)
    assert isinstance(get_provider("  Ercot "), ERCOTProvider)
    assert isinstance(get_provider("  PJM  ", api_key="k"), PJMProvider)


def test_supported_providers_lists_every_market():
    assert supported_providers() == ["caiso", "ercot", "pjm"]


def test_options_an_adapter_does_not_accept_are_dropped():
    """Callers iterating over regions should not branch per provider."""

    # sleep_seconds is a CAISO throttle; ERCOT and PJM must tolerate it.
    assert isinstance(get_provider("ercot", sleep_seconds=2.0), ERCOTProvider)
    assert isinstance(
        get_provider("pjm", api_key="k", sleep_seconds=2.0),
        PJMProvider,
    )

    caiso = get_provider("caiso", sleep_seconds=2.0)
    assert caiso.sleep_seconds == 2.0


## 8. Unsupported provider and unknown region errors -----------------------


def test_unsupported_provider_raises_with_the_supported_list():
    with pytest.raises(UnsupportedProviderError) as error:
        get_provider("miso")

    assert "miso" in str(error.value)
    assert "caiso" in str(error.value)


def test_unknown_region_raises():
    with pytest.raises(UnknownRegionError):
        get_region_config("miso_indiana_hub")


def test_supported_regions_maps_each_region_to_distinct_identifiers():
    assert supported_regions() == [
        "caiso_np15",
        "ercot_houston_hub",
        "pjm_western_hub",
    ]

    regions = [
        get_region_config(name) for name in supported_regions()
    ]

    # The market location, carbon zone and timezone are all provider-specific;
    # no identifier is reusable across regions.
    for field in ("market_location", "carbon_zone", "timezone"):
        values = [getattr(region, field) for region in regions]
        assert len(set(values)) == len(values), field

    ercot = get_region_config("ercot_houston_hub")
    assert ercot.market_provider == "ercot"
    assert ercot.market_location == "HB_HOUSTON"
    assert ercot.carbon_zone == "US-TEX-ERCO"
    assert ercot.timezone == CENTRAL
    assert ercot.carbon_provider == "electricity_maps"


## 2 & 3. Schema normalization and $/MWh -> $/kWh --------------------------


def test_caiso_normalizes_schema_and_converts_price_units(monkeypatch):
    client = FakeCAISOClient(make_caiso_frame(lmp=50.0))
    monkeypatch.setattr("gridstatus.CAISO", lambda: client)

    prices = CAISOProvider().fetch_energy_prices(
        pd.Timestamp("2026-08-25 00:00", tz=PACIFIC),
        pd.Timestamp("2026-08-25 02:00", tz=PACIFIC),
        "TH_NP15_GEN-APND",
    )

    assert list(prices.columns) == ["timestamp", "price_per_kWh"]
    # $50/MWh is $0.05/kWh.
    assert prices["price_per_kWh"].eq(0.05).all()


def test_pjm_normalizes_schema_and_converts_price_units(monkeypatch):
    monkeypatch.setattr(
        "gridstatus.PJM",
        lambda api_key: FakePJMClient(lmp=30.0),
    )

    start = pd.Timestamp.now(tz=EASTERN).normalize() - pd.Timedelta(days=2)

    prices = PJMProvider(api_key="test-key").fetch_energy_prices(
        start,
        start + pd.Timedelta(hours=1),
        "51288",
    )

    assert list(prices.columns) == ["timestamp", "price_per_kWh"]
    # $30/MWh is $0.03/kWh.
    assert prices["price_per_kWh"].round(10).eq(0.03).all()


def test_ercot_normalizes_spp_schema_and_converts_price_units(monkeypatch):
    client = FakeERCOTClient(make_ercot_frame(spp=25.0))
    monkeypatch.setattr("gridstatus.Ercot", lambda: client)

    prices = ERCOTProvider().fetch_energy_prices(
        pd.Timestamp("2026-08-25 00:00", tz=CENTRAL),
        pd.Timestamp("2026-08-25 02:00", tz=CENTRAL),
        "HB_HOUSTON",
    )

    assert list(prices.columns) == ["timestamp", "price_per_kWh"]
    # $25/MWh is $0.025/kWh.
    assert prices["price_per_kWh"].eq(0.025).all()

    # ERCOT is queried through get_spp on the 15-minute real-time market.
    assert client.calls[0]["market"].value == "REAL_TIME_15_MIN"
    assert client.calls[0]["locations"] == ["HB_HOUSTON"]


def test_ercot_reads_the_spp_column_not_lmp(monkeypatch):
    """ERCOT has no LMP column; reading the wrong one must fail loudly."""

    frame = make_ercot_frame().rename(columns={"SPP": "LMP"})
    monkeypatch.setattr(
        "gridstatus.Ercot",
        lambda: FakeERCOTClient(frame),
    )

    with pytest.raises(SchemaError) as error:
        ERCOTProvider().fetch_energy_prices(
            pd.Timestamp("2026-08-25 00:00", tz=CENTRAL),
            pd.Timestamp("2026-08-25 02:00", tz=CENTRAL),
            "HB_HOUSTON",
        )

    assert "SPP" in str(error.value)


def test_ercot_needs_no_credentials():
    assert ERCOTProvider().requires_credentials is False
    assert ERCOTProvider().credential_env_var is None


def test_ercot_configures_python_certificate_bundle(monkeypatch):
    client = FakeERCOTClient(make_ercot_frame())
    monkeypatch.setattr("gridstatus.Ercot", lambda: client)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    ERCOTProvider().fetch_energy_prices(
        pd.Timestamp("2026-08-25 00:00", tz=CENTRAL),
        pd.Timestamp("2026-08-25 01:00", tz=CENTRAL),
        "HB_HOUSTON",
    )

    assert os.environ["SSL_CERT_FILE"].endswith("cacert.pem")


def test_ercot_is_native_fifteen_minute_and_needs_no_resampling(monkeypatch):
    client = FakeERCOTClient(make_ercot_frame(periods=96))
    monkeypatch.setattr("gridstatus.Ercot", lambda: client)

    provider = ERCOTProvider()
    assert provider.native_interval_minutes == 15

    start = pd.Timestamp("2026-08-25 00:00", tz=CENTRAL)

    prices = provider.fetch_energy_prices(
        start,
        start + pd.Timedelta(days=1),
        "HB_HOUSTON",
    )

    # One row in, one row out: no averaging happened.
    assert len(prices) == 96


def test_missing_source_column_raises_schema_error():
    raw = make_caiso_frame().drop(columns=["LMP"])

    with pytest.raises(SchemaError) as error:
        base.normalize_price_frame(
            raw,
            provider_name="CAISO",
            timestamp_column="Interval Start",
            price_column="LMP",
            timezone=PACIFIC,
        )

    assert "LMP" in str(error.value)


def test_nonnumeric_price_raises_unit_conversion_error():
    raw = make_caiso_frame()
    raw["LMP"] = "not-a-price"

    with pytest.raises(UnitConversionError):
        base.normalize_price_frame(
            raw,
            provider_name="CAISO",
            timestamp_column="Interval Start",
            price_column="LMP",
            timezone=PACIFIC,
        )


def test_empty_response_raises():
    with pytest.raises(EmptyResponseError):
        base.normalize_price_frame(
            make_caiso_frame().iloc[0:0],
            provider_name="CAISO",
            timestamp_column="Interval Start",
            price_column="LMP",
            timezone=PACIFIC,
        )


## 4. Timezone normalization ----------------------------------------------


def test_pjm_timestamps_land_in_eastern_not_pacific(monkeypatch):
    monkeypatch.setattr(
        "gridstatus.PJM",
        lambda api_key: FakePJMClient(),
    )

    start = pd.Timestamp.now(tz=EASTERN).normalize() - pd.Timedelta(days=2)

    prices = PJMProvider(api_key="test-key").fetch_energy_prices(
        start,
        start + pd.Timedelta(hours=1),
        "51288",
    )

    assert str(prices["timestamp"].dt.tz) == EASTERN


def test_ercot_timestamps_land_in_central(monkeypatch):
    monkeypatch.setattr(
        "gridstatus.Ercot",
        lambda: FakeERCOTClient(make_ercot_frame()),
    )

    prices = ERCOTProvider().fetch_energy_prices(
        pd.Timestamp("2026-08-25 00:00", tz=CENTRAL),
        pd.Timestamp("2026-08-25 02:00", tz=CENTRAL),
        "HB_HOUSTON",
    )

    assert str(prices["timestamp"].dt.tz) == CENTRAL


def test_caiso_timestamps_stay_in_pacific(monkeypatch):
    client = FakeCAISOClient(make_caiso_frame())
    monkeypatch.setattr("gridstatus.CAISO", lambda: client)

    prices = CAISOProvider().fetch_energy_prices(
        pd.Timestamp("2026-08-25 00:00", tz=PACIFIC),
        pd.Timestamp("2026-08-25 02:00", tz=PACIFIC),
        "TH_NP15_GEN-APND",
    )

    assert str(prices["timestamp"].dt.tz) == PACIFIC


def test_naive_request_window_is_localized_to_the_provider_timezone():
    start, end = base.require_aware_timestamps(
        "2026-08-25 00:00",
        "2026-08-26 00:00",
        EASTERN,
    )

    assert str(start.tz) == EASTERN
    assert str(end.tz) == EASTERN


def test_backwards_window_is_rejected():
    with pytest.raises(RangeLimitError):
        base.require_aware_timestamps(
            "2026-08-26 00:00",
            "2026-08-25 00:00",
            EASTERN,
        )


## 5 & 6. Multi-chunk concatenation and boundary de-duplication -----------


def test_pjm_fetches_in_chunks_and_joins_them_without_duplicates(monkeypatch):
    client = FakePJMClient(inclusive_end=True)
    monkeypatch.setattr("gridstatus.PJM", lambda api_key: client)

    provider = PJMProvider(api_key="test-key")
    provider.max_chunk_days = 1

    start = pd.Timestamp.now(tz=EASTERN).normalize() - pd.Timedelta(days=5)
    end = start + pd.Timedelta(days=3)

    prices = provider.fetch_energy_prices(start, end, "51288")

    # Three one-day chunks were requested.
    assert len(client.calls) == 3

    # The inclusive-end rows overlapped, but none survive in the output.
    assert prices["timestamp"].is_unique
    assert prices["timestamp"].is_monotonic_increasing

    # 3 days of 15-minute intervals, with no DST transition in the window.
    assert len(prices) == 3 * 96


def test_combine_chunks_drops_repeated_boundary_intervals():
    first = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                pd.Timestamp("2026-08-25 00:00", tz=EASTERN),
                periods=4,
                freq="15min",
            ),
            "price_per_kWh": [0.01, 0.02, 0.03, 0.04],
        }
    )

    # Second chunk repeats the last interval of the first.
    second = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                pd.Timestamp("2026-08-25 00:45", tz=EASTERN),
                periods=4,
                freq="15min",
            ),
            "price_per_kWh": [0.04, 0.05, 0.06, 0.07],
        }
    )

    combined = base.combine_chunks(
        [first, second],
        provider_name="PJM",
    )

    assert len(combined) == 7
    assert combined["timestamp"].is_unique
    assert combined["timestamp"].is_monotonic_increasing


def test_iterate_chunks_produces_half_open_windows():
    start = pd.Timestamp("2026-08-25 00:00", tz=EASTERN)
    end = start + pd.Timedelta(days=5)

    chunks = list(base.iterate_chunks(start, end, max_chunk_days=2))

    assert len(chunks) == 3
    assert chunks[0][1] == chunks[1][0]
    assert chunks[-1][1] == end


def test_iterate_chunks_without_a_limit_yields_one_window():
    start = pd.Timestamp("2026-08-25 00:00", tz=PACIFIC)
    end = start + pd.Timedelta(days=40)

    assert list(base.iterate_chunks(start, end, None)) == [(start, end)]


## Resampling 5-minute PJM data onto the 15-minute grid --------------------


def test_five_minute_prices_average_into_fifteen_minute_intervals():
    timestamps = pd.date_range(
        pd.Timestamp("2026-08-25 00:00", tz=EASTERN),
        periods=6,
        freq="5min",
    )

    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_per_kWh": [0.01, 0.02, 0.03, 0.10, 0.20, 0.30],
        }
    )

    resampled = base.resample_to_target_interval(
        data,
        native_interval_minutes=5,
        provider_name="PJM",
    )

    assert len(resampled) == 2
    assert resampled["price_per_kWh"].iloc[0] == pytest.approx(0.02)
    assert resampled["price_per_kWh"].iloc[1] == pytest.approx(0.20)


def test_hourly_data_cannot_be_upsampled_to_fifteen_minutes():
    data = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                pd.Timestamp("2026-08-25 00:00", tz=EASTERN),
                periods=3,
                freq="h",
            ),
            "price_per_kWh": [0.01, 0.02, 0.03],
        }
    )

    with pytest.raises(RangeLimitError):
        base.resample_to_target_interval(
            data,
            native_interval_minutes=60,
            provider_name="PJM",
        )


## 7. Missing-interval and duplicate detection ----------------------------


def test_missing_interval_is_detected():
    timestamps = pd.date_range(
        pd.Timestamp("2026-08-25 00:00", tz=PACIFIC),
        periods=5,
        freq="15min",
    ).delete(2)

    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_per_kWh": 0.05,
        }
    )

    with pytest.raises(MissingIntervalError):
        base.check_intervals(data, provider_name="CAISO")


def test_duplicate_interval_is_rejected():
    timestamps = pd.date_range(
        pd.Timestamp("2026-08-25 00:00", tz=PACIFIC),
        periods=3,
        freq="15min",
    )

    data = pd.DataFrame(
        {
            "timestamp": timestamps.append(timestamps[[1]]).sort_values(),
            "price_per_kWh": 0.05,
        }
    )

    with pytest.raises(DuplicateIntervalError):
        base.check_intervals(data, provider_name="CAISO")


def test_timezone_naive_timestamps_are_rejected():
    data = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-08-25 00:00",
                periods=3,
                freq="15min",
            ),
            "price_per_kWh": 0.05,
        }
    )

    with pytest.raises(TimezoneNormalizationError):
        base.check_intervals(data, provider_name="CAISO")


## Daylight-saving behaviour ----------------------------------------------


def test_spring_forward_day_has_92_intervals_not_96(monkeypatch):
    """A 23-hour local day must not be rejected for having too few rows."""

    client = FakePJMClient(inclusive_end=False)
    monkeypatch.setattr("gridstatus.PJM", lambda api_key: client)

    provider = PJMProvider(api_key="test-key")
    # Bypass the archive window so a fixed historical DST date can be used.
    monkeypatch.setattr(provider, "_check_archive_window", lambda start: None)

    # 8 March 2026 is the US spring-forward transition.
    start = pd.Timestamp("2026-03-08 00:00", tz=EASTERN)
    end = pd.Timestamp("2026-03-09 00:00", tz=EASTERN)

    prices = provider.fetch_energy_prices(start, end, "51288")

    assert len(prices) == 92
    assert prices["timestamp"].is_unique


def test_validate_price_data_accepts_a_short_dst_day():
    timestamps = pd.date_range(
        start=pd.Timestamp("2026-03-08 00:00", tz=EASTERN),
        end=pd.Timestamp("2026-03-09 00:00", tz=EASTERN),
        freq="15min",
        inclusive="left",
    )

    data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_per_kWh": 0.05,
        }
    )

    assert len(data) == 92

    # No expected_rows argument, so the 96-per-day assumption never applies.
    gsd.validate_price_data(data, expected_timezone=EASTERN)


## Credentials and location validation ------------------------------------


def test_missing_pjm_credentials_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("PJM_API_KEY", raising=False)

    provider = PJMProvider()
    start = pd.Timestamp.now(tz=EASTERN).normalize() - pd.Timedelta(days=2)

    with pytest.raises(MissingCredentialsError) as error:
        provider.fetch_energy_prices(
            start,
            start + pd.Timedelta(hours=1),
            "51288",
        )

    assert "PJM_API_KEY" in str(error.value)


def test_missing_credentials_error_does_not_leak_the_key(monkeypatch):
    monkeypatch.setenv("PJM_API_KEY", "super-secret-value")

    provider = PJMProvider()

    assert "super-secret-value" not in repr(provider._build_client)


def test_pjm_rejects_a_caiso_style_node_name():
    provider = PJMProvider(api_key="test-key")
    start = pd.Timestamp.now(tz=EASTERN).normalize() - pd.Timedelta(days=2)

    with pytest.raises(InvalidLocationError) as error:
        provider.fetch_energy_prices(
            start,
            start + pd.Timedelta(hours=1),
            "TH_NP15_GEN-APND",
        )

    assert "pnode" in str(error.value)


def test_ercot_rejects_a_pjm_style_numeric_pnode_id():
    with pytest.raises(InvalidLocationError) as error:
        ERCOTProvider().fetch_energy_prices(
            pd.Timestamp("2026-08-25 00:00", tz=CENTRAL),
            pd.Timestamp("2026-08-25 02:00", tz=CENTRAL),
            "51288",
        )

    assert "HB_HOUSTON" in str(error.value)


def test_ercot_rejects_an_empty_settlement_point():
    with pytest.raises(InvalidLocationError):
        ERCOTProvider().fetch_energy_prices(
            pd.Timestamp("2026-08-25 00:00", tz=CENTRAL),
            pd.Timestamp("2026-08-25 02:00", tz=CENTRAL),
            "",
        )


def test_pjm_rejects_windows_older_than_the_archive_limit():
    provider = PJMProvider(api_key="test-key")

    start = pd.Timestamp.now(tz=EASTERN) - pd.Timedelta(days=400)

    with pytest.raises(RangeLimitError) as error:
        provider.fetch_energy_prices(
            start,
            start + pd.Timedelta(hours=1),
            "51288",
        )

    assert "186" in str(error.value)


## 9. Existing CAISO behaviour is preserved -------------------------------


def test_caiso_compatibility_wrapper_still_returns_normalized_prices(
    monkeypatch,
):
    client = FakeCAISOClient(make_caiso_frame(periods=96, lmp=50.0))
    monkeypatch.setattr("gridstatus.CAISO", lambda: client)

    prices = gsd.get_caiso_real_time_prices_range(
        start_date="2026-08-25",
        number_of_days=1,
        location="TH_NP15_GEN-APND",
        sleep_seconds=0.0,
    )

    assert list(prices.columns) == ["timestamp", "price_per_kWh"]
    assert len(prices) == 96
    assert str(prices["timestamp"].dt.tz) == PACIFIC
    assert prices["price_per_kWh"].eq(0.05).all()

    # The CAISO adapter still asks for the 15-minute real-time market.
    assert client.calls[0]["market"].value == "REAL_TIME_15_MIN"
    assert client.calls[0]["locations"] == ["TH_NP15_GEN-APND"]


def test_caiso_price_to_dataframe_keeps_its_public_behaviour():
    prices = gsd.caiso_price_to_dataframe(make_caiso_frame(lmp=100.0))

    assert list(prices.columns) == ["timestamp", "price_per_kWh"]
    assert prices["price_per_kWh"].eq(0.1).all()
    assert str(prices["timestamp"].dt.tz) == PACIFIC


def test_validate_price_data_still_raises_valueerror_for_bad_input():
    """Existing callers catch ValueError, so the wrapper must keep raising it."""

    missing_column = pd.DataFrame({"timestamp": []})

    with pytest.raises(ValueError):
        gsd.validate_price_data(missing_column)

    duplicated = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-08-25 00:00", "2026-08-25 00:00"]
            ).tz_localize(PACIFIC),
            "price_per_kWh": [0.05, 0.05],
        }
    )

    with pytest.raises(ValueError):
        gsd.validate_price_data(duplicated)


def test_region_prices_route_through_the_configured_provider(monkeypatch):
    client = FakeCAISOClient(make_caiso_frame(periods=96))
    monkeypatch.setattr("gridstatus.CAISO", lambda: client)

    prices = gsd.fetch_region_prices(
        "caiso_np15",
        start_date="2026-08-25",
        number_of_days=1,
        sleep_seconds=0.0,
    )

    assert len(prices) == 96
    assert str(prices["timestamp"].dt.tz) == PACIFIC


def test_ercot_region_prices_route_through_the_ercot_adapter(monkeypatch):
    """The same region entry point works for a provider that ignores sleep."""

    client = FakeERCOTClient(
        make_ercot_frame(start_utc="2026-08-25 05:00", periods=96)
    )
    monkeypatch.setattr("gridstatus.Ercot", lambda: client)

    prices = gsd.fetch_region_prices(
        "ercot_houston_hub",
        start_date="2026-08-25",
        number_of_days=1,
        sleep_seconds=0.0,
    )

    assert len(prices) == 96
    assert str(prices["timestamp"].dt.tz) == CENTRAL
    assert prices["timestamp"].iloc[0] == pd.Timestamp(
        "2026-08-25 00:00", tz=CENTRAL
    )
