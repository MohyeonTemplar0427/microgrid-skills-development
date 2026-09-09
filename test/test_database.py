"""Tests for database transformation utilities."""

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
import mysql.connector
from unittest.mock import MagicMock
from src.database.connector import (
    create_dispatch_result_rows,
    create_powerflow_result_rows,
    create_measurement_rows,
    upsert_measurement_rows,
    UPSERT_MEASUREMENTS_SQL,
)

# Verify one wide DataFrame interval becomes five normalized rows.
def test_create_measurement_rows_normalizes_one_interval():
    market_data = pd.DataFrame(
        {
            "timestamp": [
                "2026-08-25T00:00:00-07:00",
            ],
            "load_kw": [15.0],
            "pv_kw": [0.0],
            "net_load_kw": [15.0],
            "price_per_kWh": [0.06127028],
            "gCO2/kWh": [345.0],
        }
    )

    rows = create_measurement_rows(
        market_data,
        signal_source_id=1,
    )

    assert rows == [
        (
            1,
            datetime(2026, 8, 25, 7, 0),
            "load",
            Decimal("15.0"),
            "kW",
        ),
        (
            1,
            datetime(2026, 8, 25, 7, 0),
            "pv",
            Decimal("0.0"),
            "kW",
        ),
        (
            1,
            datetime(2026, 8, 25, 7, 0),
            "net_load",
            Decimal("15.0"),
            "kW",
        ),
        (
            1,
            datetime(2026, 8, 25, 7, 0),
            "energy_price",
            Decimal("0.06127028"),
            "$/kWh",
        ),
        (
            1,
            datetime(2026, 8, 25, 7, 0),
            "carbon_intensity",
            Decimal("345.0"),
            "gCO2/kWh",
        ),
    ]

# Reject invalid database identifiers before processing data.
def test_create_measurement_rows_rejects_nonpositive_source_id():
    market_data = pd.DataFrame()

    with pytest.raises(
        ValueError,
        match="signal_source_id must be positive",
    ):
        create_measurement_rows(
            market_data,
            signal_source_id=0,
        )

# Reject input data when a required measurement column is absent.
def test_create_measurement_rows_rejects_missing_columns():
    market_data = pd.DataFrame(
        {
            "timestamp": [
                "2026-08-25T00:00:00-07:00",
            ],
            "load_kw": [15.0],
            # pv_kw is intentionally missing.
            "net_load_kw": [15.0],
            "price_per_kWh": [0.06127028],
            "gCO2/kWh": [345.0],
        }
    )

    with pytest.raises(
        ValueError,
        match="Measurement columns missing",
    ):
        create_measurement_rows(
            market_data,
            signal_source_id=1,
        )


# Reject timestamps whose timezone is unknown.
def test_create_measurement_rows_rejects_naive_timestamp():
    market_data = pd.DataFrame(
        {
            # This timestamp has no UTC offset.
            "timestamp": ["2026-08-25 00:00:00"],
            "load_kw": [15.0],
            "pv_kw": [0.0],
            "net_load_kw": [15.0],
            "price_per_kWh": [0.06127028],
            "gCO2/kWh": [345.0],
        }
    )

    with pytest.raises(
        ValueError,
        match="must include timezone information",
    ):
        create_measurement_rows(
            market_data,
            signal_source_id=1,
        )

# NEW: Verify that a successful database batch is committed.
def test_upsert_measurement_rows_commits_successful_batch():
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor.return_value.__enter__.return_value = (
        cursor
    )

    measurement_rows = [
        (
            1,
            datetime(2026, 8, 25, 7, 0),
            "load",
            Decimal("15.0"),
            "kW",
        )
    ]

    processed_count = upsert_measurement_rows(
        connection,
        measurement_rows,
    )

    cursor.executemany.assert_called_once_with(
        UPSERT_MEASUREMENTS_SQL,
        measurement_rows,
    )
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()
    assert processed_count == 1


# Roll back the batch when MySQL rejects a write.
def test_upsert_measurement_rows_rolls_back_failed_batch():
    connection = MagicMock()
    cursor = MagicMock()

    connection.cursor.return_value.__enter__.return_value = (
        cursor
    )

    cursor.executemany.side_effect = (
        mysql.connector.Error(
            "Simulated database failure."
        )
    )

    measurement_rows = [
        (
            1,
            datetime(2026, 8, 25, 7, 0),
            "load",
            Decimal("15.0"),
            "kW",
        )
    ]

    with pytest.raises(
        mysql.connector.Error,
        match="Simulated database failure",
    ):
        upsert_measurement_rows(
            connection,
            measurement_rows,
        )

    connection.rollback.assert_called_once_with()
    connection.commit.assert_not_called()


# Avoid database activity when there are no rows to process.
def test_upsert_measurement_rows_skips_empty_batch():
    # Arrange
    connection = MagicMock()

    # Act
    processed_count = upsert_measurement_rows(
        connection,
        [],
    )

    # Assert
    assert processed_count == 0
    connection.cursor.assert_not_called()
    connection.commit.assert_not_called()
    connection.rollback.assert_not_called()


# Verify one dispatch interval becomes one normalized row.
def test_create_dispatch_result_rows_normalizes_one_interval():
    dispatch_data = pd.DataFrame(
        {
            "timestamp": [
                "2026-08-25T00:00:00-07:00",
            ],
            "battery_charge_kw": [2.0],
            "battery_discharge_kw": [0.0],
            "battery_net_injection_kw": [-2.0],
            "battery_soc_kWh": [12.0],
            "grid_import_kw": [17.0],
            "grid_export_kw": [0.0],
            "grid_net_import_kw": [17.0],
        }
    )

    rows = create_dispatch_result_rows(
        dispatch_data,
        simulation_run_id=1,
        scenario_name="cost_optimal",
    )

    assert rows == [
        (
            1,
            "cost_optimal",
            datetime(2026, 8, 25, 7, 0),
            Decimal("2.0"),
            Decimal("0.0"),
            Decimal("-2.0"),
            Decimal("12.0"),
            Decimal("17.0"),
            Decimal("0.0"),
            Decimal("17.0"),
        )
    ]

# Link one OpenDSS result to its dispatch database ID.
def test_create_powerflow_result_rows_links_dispatch_id():
    project_root = Path(__file__).resolve().parents[1]

    qsts_data = pd.read_csv(
        project_root
        / "results"
        / "week4_qsts_no_battery_15min.csv",
        nrows=1,
    )

    # CHANGED: Use an independently known expected UTC value.
    timestamp_utc = datetime(2026, 8, 25, 7, 0)

    dispatch_id_map = {
        ("no_battery", timestamp_utc): 123,
    }

    rows = create_powerflow_result_rows(
        qsts_data,
        "no_battery",
        dispatch_id_map,
    )

    assert len(rows) == 1
    assert len(rows[0]) == 22
    assert rows[0][0] == 123
    assert rows[0][1] is True
    assert rows[0][7] == Decimal(
        str(qsts_data.at[0, "minimum_voltage_pu"])
    )


# Reject a QSTS row without a matching dispatch result.
def test_create_powerflow_result_rows_requires_dispatch_id():
    project_root = Path(__file__).resolve().parents[1]

    qsts_data = pd.read_csv(
        project_root
        / "results"
        / "week4_qsts_no_battery_15min.csv",
        nrows=1,
    )

    with pytest.raises(
        ValueError,
        match="Dispatch result ID was not found",
    ):
        create_powerflow_result_rows(
            qsts_data,
            "no_battery",
            {},
        )
