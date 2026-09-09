"""Tests for the Week 4 QSTS simulation workflow."""

from pathlib import Path

import pandas as pd

from src.dispatch.dispatch_scenarios import(
    SCENARIO_OUTPUT_FILENAMES,
)
from src.opendss.qsts_simulation import(
    save_required_qsts_results,
)

def test_save_required_qsts_resulsts(
        tmp_path: Path,
):
    replay_results = {}

    for scenario_name in SCENARIO_OUTPUT_FILENAMES:
        replay_results[scenario_name] = pd.DataFrame(
            {
                "converged": [True],
            }
        )

    scenario_comparison = pd.DataFrame(
        {
            "scenrio": list(replay_results),
        }
    )

    result_paths, comparison_path = (
        save_required_qsts_results(
            replay_results,
            scenario_comparison,
            tmp_path,
        )
    )

    assert set(result_paths) == set(
        SCENARIO_OUTPUT_FILENAMES
    )

    for scenario_name, output_path in (
        result_paths.items()
    ):
        assert output_path == (
            tmp_path
            /f"week4_qsts_{scenario_name}_15min.csv"
        )

        assert output_path.is_file()

    assert comparison_path == (
        tmp_path
        / "week4_qsts_scenario_comparison.csv"
    )

    assert comparison_path.is_file()
