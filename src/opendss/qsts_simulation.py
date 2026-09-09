"""Load, replay, compare, and save OpenDSS QSTS scenarios."""

## Package import ##########################################################
from pathlib import Path
import pandas as pd


from .opendss_analysis import (
    replay_dispatch_timeseries,
)

from ..dispatch.battery import Battery

from .qsts_analysis import (
    create_qsts_scenario_comparison,
)

from ..dispatch.dispatch_scenarios import (
    SCENARIO_OUTPUT_FILENAMES,
)
###########################################################################

def load_required_dispatch_scenarios(
        input_directory: Path,
) -> dict[str, pd.DataFrame]:

    """Load every required OpenDSS dispatch schedule."""
    schedules = {}

    for scenario_name, filename in (
        SCENARIO_OUTPUT_FILENAMES.items()
    ):
        input_path = input_directory / filename

        if not input_path.is_file():
            raise FileNotFoundError(
                "Dispatch scenario file was not found: "
                f"{input_path}"
            )

        schedules[scenario_name] = pd.read_csv(
            input_path,
            parse_dates=["timestamp"],
        )

    return schedules

# load the saved electrical results for all five scenarios.
def load_required_qsts_results(
    input_directory: Path,
) -> dict[str, pd.DataFrame]:
    """Load every required saved QSTS result file."""

    qsts_results = {}

    for scenario_name in SCENARIO_OUTPUT_FILENAMES:
        input_path = (
            input_directory
            / f"week4_qsts_{scenario_name}_15min.csv"
        )

        if not input_path.is_file():
            raise FileNotFoundError(
                "QSTS result file was not found: "
                f"{input_path}"
            )

        qsts_results[scenario_name] = pd.read_csv(
            input_path,
            parse_dates=["timestamp"],
        )

    return qsts_results

def replay_required_dispatch_scenarios(
        dispatch_scenarios: dict[str, pd.DataFrame],
        *,
        battery: Battery,
        pv_capacity_kw: float,
) -> dict[str, pd.DataFrame]:
    """Replay every dispatch scenario with common equipment."""
    if not isinstance(battery, Battery):
        raise TypeError(
            "battery must be a Battery object."
        )

    if pv_capacity_kw <= 0:
        raise ValueError(
            "PV capacity must be positive."
        )

    if not dispatch_scenarios:
        raise ValueError(
            "At least one dispatch scenario is required."
        )

    replay_results = {}

    for scenario_name, dispatch_data in (
        dispatch_scenarios.items()
    ):
        replay_results[scenario_name] = (
            replay_dispatch_timeseries(
                dispatch_data,
                battery=battery,
                pv_capacity_kw=pv_capacity_kw,
            )
        )

    return replay_results

def run_required_qsts_analysis(
        input_directory: Path,
        *,
        battery: Battery,
        pv_capacity_kw: float,
        timestep_hours: float = 0.25,
) -> tuple[
    dict[str, pd.DataFrame],
    pd.DataFrame,
]:
    """Load, replay, and compare all required QSTS scenarios."""

    dispatch_scenarios = (
        load_required_dispatch_scenarios(
            input_directory
        )
    )

    replay_results = (
        replay_required_dispatch_scenarios(
            dispatch_scenarios,
            battery=battery,
            pv_capacity_kw=pv_capacity_kw,
        )
    )

    scenario_comparison = (
        create_qsts_scenario_comparison(
            replay_results,
            timestep_hours=timestep_hours,
        )
    )

    return replay_results, scenario_comparison

def save_required_qsts_results(
        replay_results: dict[str, pd.DataFrame],
        scenario_comparison: pd.DataFrame,
        output_directory: Path,
) -> tuple[dict[str, Path], Path]:

    """Save the required QSTS results and their comparison."""

    expected_names = set(
        SCENARIO_OUTPUT_FILENAMES
    )

    received_names = set(
        replay_results
    )

    if received_names != expected_names:
        raise ValueError(
            "QSTS scenario names don't match: "
            f"expected={sorted(expected_names)},"
            f"received={sorted(received_names)}"
        )

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    saved_result_paths = {}

    for scenario_name, results in (
        replay_results.items()
    ):
        output_path = (
            output_directory
            / f"week4_qsts_{scenario_name}_15min.csv"
        )

        results.to_csv(
            output_path,
            index=False,
        )

        saved_result_paths[scenario_name] = (
            output_path
        )

    comparison_path = (
        output_directory
        / "week4_qsts_scenario_comparison.csv"
    )

    scenario_comparison.to_csv(
        comparison_path,
        index=False,
    )

    return saved_result_paths, comparison_path
