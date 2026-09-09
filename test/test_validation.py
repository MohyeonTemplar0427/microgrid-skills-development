"""Tests for the combined microgrid validation report."""

import pandas as pd

from pathlib import Path

from src.dispatch.dispatch_scenarios import(
    SCENARIO_OUTPUT_FILENAMES,
)
from src.opendss.validation import(
    create_validation_report,
    create_opendss_validation_checklist,
    save_validation_artifacts, 
)


def test_create_validation_report():
    scenario_names = list(
        SCENARIO_OUTPUT_FILENAMES
    )

    dispatch_summary = pd.DataFrame(
        {
            "scenario": scenario_names,
            "grid_import_energy_kWh": [
                100.0,
                90.0,
                80.0,
                70.0,
                60.0,
            ],
            "energy_cost": [
                20.0,
                18.0,
                16.0,
                14.0,
                12.0,
            ],
        }
    )

    qsts_summary = pd.DataFrame(
        {
            "scenario": scenario_names,
            "grid_import_energy_kWh": [
                101.0,
                91.0,
                81.0,
                71.0,
                61.0,
            ],
            "grid_export_energy_kWh": [
                5.0,
                4.0,
                3.0,
                2.0,
                1.0
            ],
            "feasible_intervals": [
                192,
                192,
                192,
                192,
                192,
            ],
        }
    )

    report = create_validation_report(
        dispatch_summary,
        qsts_summary,
    )

    assert len(report) == 5

    assert (
        "scheduled_grid_import_energy_kWh"
        in report.columns
    )

    assert (
        "pcc_grid_import_energy_kWh"
        in report.columns
    )

    assert (
        "pcc_grid_export_energy_kWh"
        in report.columns
    )

    no_battery = report.loc[
        report["scenario"] == "no_battery"
    ].iloc[0]

    assert (
        no_battery[
            "scheduled_grid_import_energy_kWh"
        ]
        == 100.0
    )

    assert (
        no_battery[
            "pcc_grid_import_energy_kWh"
        ]
        == 101.0
    )

def test_create_opendss_validation_checklist():
    scenario_names = list(
        SCENARIO_OUTPUT_FILENAMES
    )

    scenario_count = len(scenario_names)

    validation_report = pd.DataFrame(
        {
            "scenario": scenario_names,
            "interval_count": (
                [192] * scenario_count
            ),
            "converged_intervals": (
                [192] * scenario_count
            ),
            "feasible_intervals": (
                [192] * scenario_count
            ),
            "minimum_voltage_pu": (
                [0.99] * scenario_count
            ),
            "maximum_voltage_pu": (
                [1.01] * scenario_count
            ),
            "maximum_line_loading_percent": (
                [50.0] * scenario_count
            ),
            "maximum_transformer_loading_percent": (
                [60.0] * scenario_count
            ),
            "feeder_loss_energy_kWh": (
                [1.0] * scenario_count
            ),
            "transformer_loss_energy_kWh": (
                [2.0] * scenario_count
            ),
            "reverse_power_flow_intervals": (
                [0] * scenario_count
            ),
            "voltage_violation_intervals": (
                [0] * scenario_count
            ),
            "line_overload_intervals": (
                [0] * scenario_count
            ),
            "transformer_overload_intervals": (
                [0] * scenario_count
            ),
        }
    )

    checklist = (
        create_opendss_validation_checklist(
            validation_report,
            base_feeder_validated=True,
            solution_modes_documented=True,
        )
    )

    assert len(checklist) == 10
    assert checklist["passed"].all()


# NEW
def test_save_validation_artifacts(
    tmp_path: Path,
):
    validation_report = pd.DataFrame(
        {
            "scenario": ["no_battery"],
            "feasible_intervals": [192],
        }
    )

    validation_checklist = pd.DataFrame(
        {
            "requirement": [
                "All required scenarios replayed"
            ],
            "passed": [True],
        }
    )

    report_path, checklist_path = (
        save_validation_artifacts(
            validation_report,
            validation_checklist,
            tmp_path,
        )
    )

    assert report_path == (
        tmp_path
        / "week4_final_validation_report.csv"
    )

    assert checklist_path == (
        tmp_path
        / "week4_opendss_validation_checklist.csv"
    )

    assert report_path.is_file()
    assert checklist_path.is_file()

    saved_report = pd.read_csv(
        report_path
    )

    saved_checklist = pd.read_csv(
        checklist_path
    )

    assert saved_report.loc[
        0,
        "scenario",
    ] == "no_battery"

    assert bool(
        saved_checklist.loc[
            0,
            "passed",
        ]
    )
