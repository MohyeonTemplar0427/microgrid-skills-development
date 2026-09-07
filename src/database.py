"""MySQL connection utilities for the experiment database."""

import os
from pathlib import Path
from datetime import datetime
from decimal import Decimal
import pandas as pd

import mysql.connector
from dotenv import load_dotenv

ENV_PATH = Path(__file__).with_name(".env")

MEASUREMENT_COLUMN_METADATA = {
    "load_kw": ("load", "kW"),
    "pv_kw": ("pv", "kW"),
    "net_load_kw": ("net_load", "kW"),
    "price_per_kWh": ("energy_price", "$/kWh"),
    "gCO2/kWh": (
        "carbon_intensity",
        "gCO2/kWh",
    ),
}

def create_database_connection():
    """Open a MySQL connection using private environment settings."""

    load_dotenv(ENV_PATH)

    return mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        database=os.environ["MYSQL_DATABASE"],
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
    )


# .cursor(): creates a cursor inside the database session
# .execute(): sends one SQL statement to MySQL
# .fetchone(): retrieves the next result row as a python tuple
def get_database_identity(
        connection,
) -> tuple[str, str]:
    """Return the selected database and authenticated MySQL account."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DATABASE(), CURRENT_USER()"
        )
        result = cursor.fetchone()

    if result is None:
        raise RuntimeError(
            "MySQL returned no database identity."
        )

    database_name, current_user = result

    return(
        str(database_name),
        str(current_user),
    )

# %s: parameter placeholder. Values are supplied separately instead of being
# inserted with an f-string
# executemany(): executes one parameterized statement for multiple tuples.
# try: runs code that might fail
# except mysql.connector.Error: handles connector/database error
# raise: sends the original error back to the caller after cleanup
# commit(): permanently saves successful changes
# rollback(): cancels the entire batch if any row fails
# if not measurement rows: detects an empty collection

UPSERT_MEASUREMENTS_SQL = """
INSERT INTO measurements (
    signal_source_id,
    measured_at_utc,
    measurement_name,
    measurement_value,
    unit
)
VALUES (%s, %s, %s, %s, %s) AS new
ON DUPLICATE KEY UPDATE
    measurement_value = new.measurement_value,
    unit = new.unit
"""
# save a batch atomically so partial measurement loads cannot remain
def upsert_measurement_rows(
    connection,
    measurement_rows,
) -> int:
    """Insert or update a collection of normalized measurements."""

    if not measurement_rows:
        return 0

    try:
        with connection.cursor() as cursor:
            cursor.executemany(
                UPSERT_MEASUREMENTS_SQL,
                measurement_rows,
            )

        connection.commit()

    except mysql.connector.Error:
        connection.rollback()
        raise

    return len(measurement_rows)


# mapping dictionary connects each CSV column to its databaase name and unit.

# .items(): provides each dictionary key and its associated value

# iterrows(): visits one DataFrame row at a time

# Decimal(str(value)) preserves decimal values more reliably than seding
# a binary float

# tz_convert("UTC"): converts the timestamp to UTC

# tz_localize(None): removes timezone metadata after conversion because
# MySQL DATETIME does not store a timezone
def create_measurement_rows(
    market_data: pd.DataFrame,
    signal_source_id: int,
) -> list[
    tuple[int, datetime, str, Decimal, str]
]:
    """Convert market data into rows accepted by MySQL."""

    if signal_source_id <= 0:
        raise ValueError(
            "signal_source_id must be positive."
        )

    missing_columns = (
        set(MEASUREMENT_COLUMN_METADATA)
        - set(market_data.columns)
    )

    if missing_columns:
        raise ValueError(
            "Measurement columns missing: "
            f"{sorted(missing_columns)}"
        )

    measurement_rows = []

    for _, interval in market_data.iterrows():
        timestamp = pd.Timestamp(
            interval["timestamp"]
        )

        if timestamp.tzinfo is None:
            raise ValueError(
                "Measurement timestamp must "
                "include timezone information."
            )

        timestamp_utc = (
            timestamp.tz_convert("UTC").tz_localize(None).to_pydatetime()
        )

        for (
            source_column, (measurement_name, unit),
        ) in MEASUREMENT_COLUMN_METADATA.items():
            measurement_rows.append(
                (
                    signal_source_id,
                    timestamp_utc,
                    measurement_name,
                    Decimal(
                        str(interval[source_column])
                    ),
                    unit,
                )
            )
    return measurement_rows
