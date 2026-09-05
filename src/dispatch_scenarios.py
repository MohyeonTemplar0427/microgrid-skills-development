"""Build the dispatch-strategy scenarios for Week 4."""

import pandas as pd

from .opendss_handoff import create_opendss_handoff
from.qsts_analysis import(
    create_no_battery_replay_schedule,
)

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

def create_optimized_dispatch_scenarios(
        data:pd.DataFrame,
        battery_parameters: dict[str, float],
        *,
        carbon_weight: float,
        degradation_cost_per_kWh: float,
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

    return {
        "rule_based": sda.run_rule_based_dispatch(
            data.copy(),
            battery_parameters,
            strategy="price",
        ),
        # In this cost_optimal case, we don't use cost_optimization function
        # that we consider degradtion parameter for optimization.
        "cost_optimal": sda.run_cost_optimization(
            data.copy(),
            battery_parameters,
            degradation_cost_per_kWh=(
                degradation_cost_per_kWh
            ),
        ),

        "carbon_optimal": sda.run_carbon_optimization(
            data.copy(),
            battery_parameters,
        ),

        "combined_optimal": sda.run_combined_optimization(
            data.copy(),
            battery_parameters,
            carbon_weight=carbon_weight,
            degradation_cost_per_kWh=(
                degradation_cost_per_kWh
            ),
        ),
    }


def create_required_dispatch_scenarios(
        data:pd.DataFrame,
        battery_parameters: dict[str, float],
        *,
        carbon_weight: float,
        degradation_cost_per_kWh: float,
        time_step_minutes: int = 15,
        expected_timezone: str = "America/Los_Angeles",
) -> dict[str, pd.DataFrame]:
    """Create all five OpenDSS-ready Week 4 schedules."""

    optimized_scenarios = (
        create_optimized_dispatch_scenarios(
            data,
            battery_parameters,
            carbon_weight=carbon_weight,
            degradation_cost_per_kWh=(degradation_cost_per_kWh),
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

    ## Remove battery operation
    no_battery = create_no_battery_replay_schedule(
        opendss_scenarios["combined_optimal"]
    )

    # Replay interface requires SOC even for no-battery, so put in fake value
    no_battery["battery_soc_kWh"] = (
        battery_parameters["initial_soc_kWh"]
    )

    return {
        "no_battery": no_battery,
        **opendss_scenarios,
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
