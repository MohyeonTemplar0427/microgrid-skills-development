import requests
import os
import pandas as pd
from dotenv import load_dotenv
from .timeseries_validation import merge_complete_time_series

load_dotenv()

api_key = os.getenv(
    "ELECTRICITY_MAPS_API_KEY"
)

pd.set_option(
    "display.max_columns",
    None,
)

#Return Carbon intensity for set range with granularity set manually inside the function
def get_carbon_intensity_range(
    api_key: str,
    zone: str,
    start: str,
    end: str,
) -> dict:
    
    url = (
        "https://api.electricitymaps.com/"
        "v4/carbon-intensity/past-range"
    )

    headers = {
        "auth-token": api_key
    }

    params = {
        "zone": zone,
        "start": start,
        "end": end,
        "temporalGranularity": "15_minutes",
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def carbon_range_to_dataframe(
        result: dict,
        timezone: str = "America/Los_Angeles",
) -> pd.DataFrame:

    data = pd.DataFrame(
        result["data"]
    )

    missing_columns = {
        "datetime",
        "carbonIntensity",
    } - set(data.columns)

    if missing_columns:
        raise ValueError(
            f"Electricity Maps response is missing columns: "
            f"{sorted(missing_columns)}."
        )

    data = data[
        [
            "datetime",
            "carbonIntensity",
        ]
    ].copy()

    data = data.rename(
        columns={
            "datetime": "timestamp",
            "carbonIntensity": "gCO2/kWh",
        }
    )

    data["timestamp"] = pd.to_datetime(
        data["timestamp"],
        utc=True,
    )

    data["timestamp"] = (
        data["timestamp"]
        .dt.tz_convert(
            timezone
        )
    )

    return data


def calculate_emissions_with_external_carbon(
        dispatch_data: pd.DataFrame,
        carbon_data: pd.DataFrame,
        timestep_hours: float = 0.25,
) -> float:

    dispatch_intervals = dispatch_data[
        [
            "timestamp",
        "grid_import_kw",
        ]
    ].copy()

    evaluation_data = merge_complete_time_series(
        dispatch_intervals,
        carbon_data,
        right_name="Carbon"
    )

    emissions_kgCO2 = (
        (
            evaluation_data["grid_import_kw"]
            * timestep_hours
            * evaluation_data["gCO2/kWh"]
        ).sum()
        / 1000
    )

    return float(emissions_kgCO2)

def validate_carbon_data(
        data: pd.DataFrame,
        expected_rows: int | None = None,
        timestep_minutes: int = 15,
        expected_timezone: str = "America/Los_Angeles",
) -> None:

    required_columns = {
        "timestamp",
        "gCO2/kWh",
    }

    missing_columns = (
        required_columns
        - set(data.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Missing required column: {missing_columns}"
        )

    if data.empty:
        raise ValueError(
            "Carbon data is empty."
        )

    if expected_rows is not None:
        if len(data) != expected_rows:
            raise ValueError(
                f"Expected {expected_rows} rows. "
                f"but received {len(data)}."
            )

    if data.isna().any().any():
        raise ValueError(
            "Carbon data contains missing values."
        )

    if not data["timestamp"].is_unique:
        raise ValueError(
            "Duplicate timestamps found."
        )

    if not data["timestamp"].is_monotonic_increasing:
        raise ValueError(
            "Timestamps are not increaasing"
        )
    
    time_differences = (
        data["timestamp"]
        .diff()
        .dropna()
    )

    expected_timestep = pd.Timedelta(
        minutes=timestep_minutes
    )

    if not (time_differences == expected_timestep).all():
        raise ValueError(
            "Carbon data does not have continuous 15-minute timestamps."
        )

    timezone = data["timestamp"].dt.tz

    if timezone is None:
        raise ValueError(
            "Time stamps are not timezone-aware"
        )

    if str(timezone) != expected_timezone:
        raise ValueError(
            f"Expected timezone {expected_timezone} but received {timezone}."
        )

    if (data["gCO2/kWh"] < 0).any():
        raise ValueError(
            "Carbon Intensity cannot be negative"
        )


#Helper Function for creating multi-day time range
def create_utc_time_range(
        start_date: str,
        number_of_days: int,
        timezone: str = "America/Los_Angeles",
    ) -> tuple[str, str]:

    local_start = pd.Timestamp(
        start_date,
        tz=timezone,
    )

    # DateOffset advances local calendar days; Timedelta would add exactly
    # 24 hours and drift by an hour across a daylight-saving transition.
    local_end = (
        local_start
        + pd.DateOffset(days=number_of_days)
    )

    utc_start = local_start.tz_convert("UTC")
    utc_end = local_end.tz_convert("UTC")

    start_string = utc_start.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    end_string = utc_end.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    return start_string, end_string


def get_multi_day_carbon_data(
        api_key: str,
        zone: str,
        start_date: str,
        number_of_days: int,
        timezone: str = "America/Los_Angeles",
    ) -> pd.DataFrame:

    if not api_key:
        raise ValueError(
            "Electricity Maps API key is missing. Set "
            "ELECTRICITY_MAPS_API_KEY in your environment or .env file."
        )

    start, end = create_utc_time_range(
            start_date,
            number_of_days,
            timezone,
        )

    result = get_carbon_intensity_range(
        api_key,
        zone,
        start,
        end,
    )

    if (
        result["temporalGranularity"] != "15_minutes"
    ):
        raise ValueError(
        "Electricity Maps did not return 15-minute data."
        )

    carbon_data = (
        carbon_range_to_dataframe(
            result,
            timezone,
        )
    )

    validate_carbon_data(
        carbon_data,
        expected_timezone=timezone,
    )

    return carbon_data
        
## Main -----------------------------------------------------------------

    




    


