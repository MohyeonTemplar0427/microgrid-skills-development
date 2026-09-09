import gridstatus
import pandas as pd
import time

LOCAL_TIMEZONE = "America/Los_Angeles"

## Fetch caiso real time price data from gridstatus
def get_caiso_real_time_prices(
        date:str,
        location: str,
) -> pd.DataFrame:

    caiso = gridstatus.CAISO()

    data = caiso.get_lmp(
        date = date,
        market="REAL_TIME_15_MIN",
        locations=[
            location
        ],
    )

    return data

def get_caiso_real_time_prices_range(
        start_date: str,
        number_of_days: int,
        location: str,
        sleep_seconds: float = 1.0
) -> pd.DataFrame:

    caiso = gridstatus.CAISO()

    start_timestamp = pd.Timestamp(
        start_date
    )

    end_timestamp = (
        start_timestamp
        + pd.Timedelta(
            days=number_of_days
        )
    )

    raw_data = caiso.get_lmp(
        date=start_timestamp,
        end=end_timestamp,
        market=gridstatus.Markets.REAL_TIME_15_MIN,
        locations=[
            location
        ],
        sleep = sleep_seconds,
    )

    price_data = (
        caiso_price_to_dataframe(
            raw_data
        )
    )

    validate_price_data(
        price_data,
        expected_rows=(
            number_of_days * 96
        ),
    )

    return price_data


## Convert price data into pandas dataframe
def caiso_price_to_dataframe(
        raw_data: pd.DataFrame,
) -> pd.DataFrame:

    data = raw_data[
        [
            "Interval Start",
            "LMP",
        ]
    ].copy()

    data = data.rename(
        columns={
            "Interval Start": "timestamp",
            "LMP": "price_per_kWh",
        }
    )

    data["timestamp"] = (
        data["timestamp"]
        .dt.tz_convert(
            "America/Los_Angeles"
        )
    )

    data["price_per_kWh"] = (
        data["price_per_kWh"]
        / 1000
    )

    return data


def validate_price_data(
    data: pd.DataFrame,
    expected_rows: int | None = None,
    timestep_minutes: int = 15,
    expected_timezone: str = "America/Los_Angeles",
) -> None:

    required_columns = {
        "timestamp",
        "price_per_kWh",
    }

    missing_columns = (
        required_columns
        - set(data.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    if data.empty:
        raise ValueError(
            "Price data is empty."
        )

    if expected_rows is not None:
        if len(data) != expected_rows:
            raise ValueError(
                f"Expected {expected_rows} rows, "
                f"but received {len(data)}."
            )

    if data.isna().any().any():
        raise ValueError(
            "Price data contains missing values."
        )

    if not data["timestamp"].is_unique:
        raise ValueError(
            "Duplicate timestamps found."
        )

    if not data[
        "timestamp"
    ].is_monotonic_increasing:
        raise ValueError(
            "Timestamps are not increasing."
        )

    time_differences = (
        data["timestamp"]
        .diff()
        .dropna()
    )

    expected_timestep = pd.Timedelta(
        minutes=timestep_minutes
    )

    if not (
        time_differences
        == expected_timestep
    ).all():
        raise ValueError(
            "Price data does not have "
            "continuous 15-minute timestamps."
        )

    timezone = (
        data["timestamp"]
        .dt.tz
    )

    if timezone is None:
        raise ValueError(
            "Timestamps are not timezone-aware."
        )

    if str(timezone) != expected_timezone:
        raise ValueError(
            f"Expected timezone {expected_timezone}, "
            f"but received {timezone}."
        )

##MAIN------------------------------------------------------------------------
if __name__ == "__main__":

    start_time = time.perf_counter()

    test_location = "TH_NP15_GEN-APND"

    raw_price_data = (
        get_caiso_real_time_prices(
            "2026-08-26",
            location=test_location,
        )
    )

    end_time = time.perf_counter()

    price_data = (
        caiso_price_to_dataframe(
            raw_price_data
        )
    )

    validate_price_data(
        price_data,
        expected_rows=96,
    )

    query_runtime = end_time - start_time

    print(
        f"CAISO query runtime: "
        f"{query_runtime:.2f} seconds"
    )
    