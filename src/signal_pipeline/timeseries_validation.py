""" Shared validation helpers for alingned time-series data."""

import pandas as pd

def merge_complete_time_series(
    left_data: pd.DataFrame,
    right_data: pd.DataFrame,
    *,
    right_name: str,
) -> pd.DataFrame:
    """
    Merge two time series with identical, unique timestamp coverage.
    
    Both DataFrames must contain exactly one row for every timestamp.
    """

    if "timestamp" not in left_data.columns:
        raise ValueError(
            "Left time series is missing the timestamp columns."
        )

    if "timestamp" not in right_data.columns:
        raise ValueError(
            f"{right_name} data is missing the timestamp columns."
        )

    try:
        merged_data = pd.merge(
            left_data,
            right_data,
            on="timestamp",
            how="inner",
            validate="one_to_one",
        )
    except pd.errors.MergeError as error:
        raise ValueError(
            f"{right_name} merge requires unique timestamps in both datasets."
        ) from error

    if (
        len(merged_data) != len(left_data)
        or len(merged_data) != len(right_data)
    ):
        raise ValueError(
            f"{right_name} data does not cover exactly the same timestamps as the existing time series."
        )

    return merged_data