"""Build the dispatch-strategy scenarios for Week 4."""

import pandas as pd

from ..analysis.no_battery import create_no_battery_dispatch
from ..opendss.opendss_handoff import create_opendss_handoff

from . import single_day_analysis as sda

from pathlib import Path
SCENARIO_OUTPUT_FILENAMES = {  # NEW
    "no_battery": (
        "week4_dispatch_no_battery_15min.csv"
    ),
    "rule_based": (
        "week4_dispatch_rule_based_15min.csv"
    ),
    "cost_optimal": (
        "week4_dispatch_cost_optimal_15min.csv"
    ),
    "carbon_optimal": (
        "week4_dispatch_carbon_optimal_15min.csv"
    ),
    "combined_optimal": (
        "week4_dispatch_combined_optimal_15min.csv"
    ),
}

OPTIMIZED_SCENARIO_NAMES = (
    "rule_based",
    "cost_optimal",
    "carbon_optimal",
    "combined_optimal",
)

def create_optimized_dispatch_scenarios(
        data:pd.DataFrame,
        battery_parameters: dict[str, float],
        *,
        carbon_weight: float,
        degradation_cost_per_kWh: float,
        scenario_names: tuple[str, ...] | None = None,
) -> dict[str, pd.DataFrame]:
    """Create rule-based and optimized dispatch schedules."""

    required_columns = {
        "timestamp",
        "load_kw",
        "pv_kw",
        "net_load_kw",
        "price_per_kWh",
        "gCO2/kWh",
    }

    missing_columns = (
        required_columns - set(data.columns)
    )

    if missing_columns:
        raise ValueError(f"Dispatch scenario data is missing columns: {sorted(missing_columns)}")

    if data.empty:
        raise ValueError(
            "Dispatch scenario data must not be empty."
        )

    if carbon_weight < 0:
        raise ValueError(
            "Carbon weight must not be negative."
        )

    if degradation_cost_per_kWh < 0:
        raise ValueError(
            "Degradation cost must not be negative."
        )

    requested_names = (
        OPTIMIZED_SCENARIO_NAMES
        if scenario_names is None
        else tuple(scenario_names)
    )
    unsupported_names = (
        set(requested_names) - set(OPTIMIZED_SCENARIO_NAMES)
    )

    if unsupported_names:
        raise ValueError(
            "Unsupported optimized scenarios: "
            f"{sorted(unsupported_names)}"
        )

    builders = {
        "rule_based": lambda: sda.run_rule_based_dispatch(
            data.copy(),
            battery_parameters,
            strategy="price",
        ),
        "cost_optimal": lambda: sda.run_cost_optimization(
            data.copy(),
            battery_parameters,
            degradation_cost_per_kWh=degradation_cost_per_kWh,
        ),
        "carbon_optimal": lambda: sda.run_carbon_optimization(
            data.copy(),
            battery_parameters,
        ),
        "combined_optimal": lambda: sda.run_combined_optimization(
            data.copy(),
            battery_parameters,
            carbon_weight=carbon_weight,
            degradation_cost_per_kWh=degradation_cost_per_kWh,
        ),
    }

    return {
        name: builders[name]()
        for name in OPTIMIZED_SCENARIO_NAMES
        if name in requested_names
    }


def create_required_dispatch_scenarios(
        data:pd.DataFrame,
        battery_parameters: dict[str, float],
        *,
        carbon_weight: float,
        degradation_cost_per_kWh: float,
        time_step_minutes: int = 15,
        expected_timezone: str = "America/Los_Angeles",
        scenario_names: tuple[str, ...] | None = None,
) -> dict[str, pd.DataFrame]:
    """Create only the requested OpenDSS-ready dispatch schedules."""

    requested_names = (
        tuple(SCENARIO_OUTPUT_FILENAMES)
        if scenario_names is None
        else tuple(scenario_names)
    )
    unsupported_names = set(requested_names) - set(
        SCENARIO_OUTPUT_FILENAMES
    )

    if not requested_names:
        raise ValueError("Select at least one dispatch scenario.")

    if unsupported_names:
        raise ValueError(
            "Unsupported dispatch scenarios: "
            f"{sorted(unsupported_names)}"
        )

    optimized_scenarios = (
        create_optimized_dispatch_scenarios(
            data,
            battery_parameters,
            carbon_weight=carbon_weight,
            degradation_cost_per_kWh=(degradation_cost_per_kWh),
            scenario_names=tuple(
                name
                for name in requested_names
                if name != "no_battery"
            ),
        )
    )

    opendss_scenarios = {
        scenario_name: create_opendss_handoff(
            schedule,
            timestep_minutes=time_step_minutes,
            expected_timezone=expected_timezone,
        )
        for scenario_name, schedule
        in optimized_scenarios.items()
    }

    if "no_battery" in requested_names:
        no_battery = create_no_battery_dispatch(data)
        no_battery["battery_soc_kWh"] = (
            battery_parameters["initial_soc_kWh"]
        )
        opendss_scenarios["no_battery"] = create_opendss_handoff(
            no_battery,
            timestep_minutes=time_step_minutes,
            expected_timezone=expected_timezone,
        )

    return {
        name: opendss_scenarios[name]
        for name in SCENARIO_OUTPUT_FILENAMES
        if name in requested_names
    }

def save_required_dispatch_scenarios(
        scnenarios: dict[str, pd.DataFrame],
        output_directory: Path,
) -> dict[str, Path]:
    """Save all required Week 4 dispatch schedules."""

    expected_names = set(
        SCENARIO_OUTPUT_FILENAMES
    )

    received_names = set(scnenarios)

    missing_names = (
        expected_names - received_names
    )

    unexpected_names = (
        received_names - expected_names
    )

    if missing_names or unexpected_names:
        raise ValueError(
            "Dispatch scenario names do not match: "
            f"missing={sorted(missing_names)}, "
            f"unexpected={sorted(unexpected_names)}"
        )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    saved_paths = {}

    for scenario_name, fileanme in(
        SCENARIO_OUTPUT_FILENAMES.items()
    ):
        output_path = (
            output_directory / fileanme
        )

        scnenarios[scenario_name].to_csv(
            output_path,
            index=False,
        )

        saved_paths[scenario_name] = (
            output_path
        )

    return saved_paths
