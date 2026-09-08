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

# Insert dispatch rows while preserving existing primary keys.
UPSERT_DISPATCH_RESULTS_SQL = """
INSERT INTO dispatch_results (
    simulation_run_id,
    scenario_name,
    dispatched_at_utc,
    battery_charge_kw,
    battery_discharge_kw,
    battery_net_injection_kw,
    battery_soc_kwh,
    grid_import_kw,
    grid_export_kw,
    grid_net_import_kw
)
VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s
) AS new
ON DUPLICATE KEY UPDATE
    battery_charge_kw = new.battery_charge_kw,
    battery_discharge_kw = new.battery_discharge_kw,
    battery_net_injection_kw =
        new.battery_net_injection_kw,
    battery_soc_kwh = new.battery_soc_kwh,
    grid_import_kw = new.grid_import_kw,
    grid_export_kw = new.grid_export_kw,
    grid_net_import_kw = new.grid_net_import_kw
"""

SELECT_DISPATCH_RESULT_IDS_SQL = """
SELECT
    dispatch_result_id,
    scenario_name,
    dispatched_at_utc
FROM dispatch_results
WHERE simulation_run_id = %s
"""

def create_dispatch_result_rows(
    dispatch_data: pd.DataFrame,
    simulation_run_id: int,
    scenario_name: str,
) -> list[tuple]:
    """Convert one dispatch scenario into MySQL result rows."""

    if simulation_run_id <= 0:
        raise ValueError(
            "simulation_run_id must be positive."
        )
    if not scenario_name.strip():
        raise ValueError(
            "scenario_name must not be empty."
        )

    required_columns = {
        "timestamp",
        "battery_charge_kw",
        "battery_discharge_kw",
        "battery_net_injection_kw",
        "battery_soc_kWh",
        "grid_import_kw",
        "grid_export_kw",
        "grid_net_import_kw",   
    }

    missing_columns = (
        required_columns - set(dispatch_data.columns)
    )

    if missing_columns:
        raise ValueError(
            "Dispatch columns missing: "
            f"{sorted(missing_columns)}"
        )

    dispatch_rows = []

    for _, interval in dispatch_data.iterrows():
        timestamp = pd.Timestamp(
            interval["timestamp"]
        )

        if timestamp.tzinfo is None:
            raise ValueError(
                "Dispatch timestamp must include timezone information."
            )

        dispatched_at_utc = (
            timestamp.tz_convert("UTC").tz_localize(None).to_pydatetime()
        )

        dispatch_rows.append(
            (
                simulation_run_id,
                scenario_name,
                dispatched_at_utc,

                Decimal(str(interval["battery_charge_kw"])),
                Decimal(str(interval["battery_discharge_kw"])),
                Decimal(str(interval["battery_net_injection_kw"])),
                Decimal(str(interval["battery_soc_kWh"])),
                Decimal(str(interval["grid_import_kw"])),
                Decimal(str(interval["grid_export_kw"])),
                Decimal(str(interval["grid_net_import_kw"])),
            )
        )

    return dispatch_rows

def upsert_dispatch_result_rows(
        connection,
        dispatch_rows,
) -> int:
    """Insert or update normalized dispatch-result rows."""
    if not dispatch_rows:
        return 0
    try:
        with connection.cursor() as cursor:
            cursor.executemany(
                UPSERT_DISPATCH_RESULTS_SQL,
                dispatch_rows,
            )

        connection.commit()
    except mysql.connector.Error:
        connection.rollback()
        raise

    return len(dispatch_rows)

def upsert_dispatch_scenarios(
        # passed into the function so multiple scenario operations can share
        # one session and tests can use a mock connection.
        connection,
        dispatch_scenarios: dict[str, pd.DataFrame],
        simulation_run_id: int,
) -> dict[str, int]:
    """Save multiple dispatch scenarios as one database batch."""

    if not dispatch_scenarios:
        raise ValueError(
            "At least one dispatch scenario is required."
        )

    all_dispatch_rows = []
    scenario_row_counts = {}

    for scenario_name, dispatch_data in (dispatch_scenarios.items()):
        scenario_rows = create_dispatch_result_rows(
            dispatch_data,
            simulation_run_id,
            scenario_name,
        )

        all_dispatch_rows.extend(scenario_rows)

        scenario_row_counts[scenario_name] = len(
            scenario_rows
        )

    upsert_dispatch_result_rows(
        connection,
        all_dispatch_rows,
    )

    return scenario_row_counts


# Build a lookup from scenario and timestamp to database ID.
def get_dispatch_result_id_map(
        connection,
        simulation_run_id: int,
) -> dict[tuple[str, datetime], int]:
    """Return the stored ID of every dispatch operating point."""

    if simulation_run_id <= 0:
        raise ValueError(
            "simulation_run_id must be positive."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            SELECT_DISPATCH_RESULT_IDS_SQL,
            (simulation_run_id,),
        )
        stored_rows = cursor.fetchall()

    dispatch_id_map = {}

    for(
        dispatch_result_id,
        scenario_name,
        dispatched_at_utc,
    ) in stored_rows:
        lookup_key = (
            str(scenario_name),
            dispatched_at_utc,
        )

        dispatch_id_map[lookup_key] = int(
            dispatch_result_id
        )

    return dispatch_id_map

def create_powerflow_result_rows(
    qsts_data: pd.DataFrame,
    scenario_name: str,
    dispatch_id_map: dict[tuple[str, datetime], int],
) -> list[tuple]:
    """Convert one QSTS scenario into MySQL power-flow rows."""

    if not scenario_name.strip():
        raise ValueError(
            "scenario_name must not be empty."
        )

    required_columns = {
        "timestamp",
        "converged",
        "voltage_violation",
        "line_overload",
        "transformer_overload",
        "reverse_power_flow",
        "feasible",
        "minimum_voltage_pu",
        "maximum_voltage_pu",
        "maximum_current_a",
        "line_normal_rating_a",
        "line_loading_percent",
        "transformer_apparent_power_kva",
        "transformer_loading_percent",
        "transformer_real_loss_kw",
        "feeder_input_real_power_kw",
        "feeder_real_loss_kw",
        "pcc_grid_net_import_kw",
        "pcc_grid_import_kw",
        "pcc_grid_export_kw",
        "receiving_end_real_power_kw",
        "grid_import_error_kw",
    }

    missing_columns = (
        required_columns - set(qsts_data.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Power-flow columns missing: {sorted(missing_columns)}"
        )

    powerflow_rows = []

    for _, interval in qsts_data.iterrows():
        timestamp = pd.Timestamp(
            interval["timestamp"]
        )

        if timestamp.tzinfo is None:
            raise ValueError(
                "Power-flow timestamp must include timezone information."
            )

        result_at_utc = (
            timestamp.tz_convert("UTC").tz_localize(None).to_pydatetime()
        )

        lookup_key = (
            scenario_name,
            result_at_utc,
        )

        if lookup_key not in dispatch_id_map:
            raise ValueError(
                "Dispatch result ID was not found for "
                f"{scenario_name} at {result_at_utc}."
            )

        dispatch_result_id = dispatch_id_map[lookup_key]

        powerflow_rows.append(
            (
                dispatch_result_id,

                bool(interval["converged"]),
                bool(interval["voltage_violation"]),
                bool(interval["line_overload"]),
                bool(interval["transformer_overload"]),
                bool(interval["reverse_power_flow"]),
                bool(interval["feasible"]),

                Decimal(str(interval["minimum_voltage_pu"])),
                Decimal(str(interval["maximum_voltage_pu"])),
                Decimal(str(interval["maximum_current_a"])),

                Decimal(str(interval["line_normal_rating_a"])),
                Decimal(str(interval["line_loading_percent"])),

                Decimal(
                    str(
                        interval[
                            "transformer_apparent_power_kva"
                        ]
                    )
                ),
                Decimal(
                    str(
                        interval[
                            "transformer_loading_percent"
                        ]
                    )
                ),
                Decimal(
                    str(
                        interval[
                            "transformer_real_loss_kw"
                        ]
                    )
                ),

                Decimal(
                    str(interval["feeder_input_real_power_kw"])
                ),
                Decimal(str(interval["feeder_real_loss_kw"])),

                Decimal(str(interval["pcc_grid_net_import_kw"])),
                Decimal(str(interval["pcc_grid_import_kw"])),
                Decimal(str(interval["pcc_grid_export_kw"])),

                Decimal(
                    str(
                        interval[
                            "receiving_end_real_power_kw"
                        ]
                    )
                ),
                Decimal(str(interval["grid_import_error_kw"])),
            )
        )

    return powerflow_rows

# Insert power-flow rows while preserving existing primary keys.
UPSERT_POWERFLOW_RESULTS_SQL = """
INSERT INTO powerflow_results (
    dispatch_result_id,
    converged,
    voltage_violation,
    line_overload,
    transformer_overload,
    reverse_power_flow,
    feasible,
    minimum_voltage_pu,
    maximum_voltage_pu,
    maximum_current_a,
    line_normal_rating_a,
    line_loading_percent,
    transformer_apparent_power_kva,
    transformer_loading_percent,
    transformer_real_loss_kw,
    feeder_input_real_power_kw,
    feeder_real_loss_kw,
    pcc_grid_net_import_kw,
    pcc_grid_import_kw,
    pcc_grid_export_kw,
    receiving_end_real_power_kw,
    grid_import_error_kw
)
VALUES (
    %s,
    %s, %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s,
    %s, %s, %s,
    %s, %s,
    %s, %s, %s,
    %s, %s
) AS new
ON DUPLICATE KEY UPDATE
    converged = new.converged,
    voltage_violation = new.voltage_violation,
    line_overload = new.line_overload,
    transformer_overload = new.transformer_overload,
    reverse_power_flow = new.reverse_power_flow,
    feasible = new.feasible,
    minimum_voltage_pu = new.minimum_voltage_pu,
    maximum_voltage_pu = new.maximum_voltage_pu,
    maximum_current_a = new.maximum_current_a,
    line_normal_rating_a = new.line_normal_rating_a,
    line_loading_percent = new.line_loading_percent,
    transformer_apparent_power_kva =
        new.transformer_apparent_power_kva,
    transformer_loading_percent =
        new.transformer_loading_percent,
    transformer_real_loss_kw =
        new.transformer_real_loss_kw,
    feeder_input_real_power_kw =
        new.feeder_input_real_power_kw,
    feeder_real_loss_kw = new.feeder_real_loss_kw,
    pcc_grid_net_import_kw =
        new.pcc_grid_net_import_kw,
    pcc_grid_import_kw = new.pcc_grid_import_kw,
    pcc_grid_export_kw = new.pcc_grid_export_kw,
    receiving_end_real_power_kw =
        new.receiving_end_real_power_kw,
    grid_import_error_kw = new.grid_import_error_kw
"""

# Save a power-flow batch as one transaction.
def upsert_powerflow_result_rows(
    connection,
    powerflow_rows,
) -> int:
    """Insert or update normalized power-flow result rows."""

    if not powerflow_rows:
        return 0

    try:
        with connection.cursor() as cursor:
            cursor.executemany(
                UPSERT_POWERFLOW_RESULTS_SQL,
                powerflow_rows,
            )

        connection.commit()

    except mysql.connector.Error:
        connection.rollback()
        raise

    return len(powerflow_rows)

# Transform and save multiple QSTS scenarios atomically.
def upsert_powerflow_scenarios(
    connection,
    qsts_results: dict[str, pd.DataFrame],
    simulation_run_id: int,
) -> dict[str, int]:
    """Save multiple QSTS scenarios as one database batch."""

    if not qsts_results:
        raise ValueError(
            "At least one QSTS result is required."
        )

    dispatch_id_map = get_dispatch_result_id_map(
        connection,
        simulation_run_id,
    )

    all_powerflow_rows = []
    scenario_row_counts = {}

    for scenario_name, qsts_data in (
        qsts_results.items()
    ):
        scenario_rows = create_powerflow_result_rows(
            qsts_data,
            scenario_name,
            dispatch_id_map,
        )

        all_powerflow_rows.extend(scenario_rows)

        scenario_row_counts[scenario_name] = len(
            scenario_rows
        )

    upsert_powerflow_result_rows(
        connection,
        all_powerflow_rows,
    )

    return scenario_row_counts
