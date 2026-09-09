"""Create the combined operational and electrical validation report."""

import pandas as pd

from ..dispatch.battery import Battery
from ..dispatch.config import to_optimizer_parameters
from pathlib import Path

from .qsts_simulation import(
    load_required_dispatch_scenarios,
)

from ..dispatch.dispatch_scenarios import(
    SCENARIO_OUTPUT_FILENAMES,
)

from ..dispatch.dispatch_metrics import(
    calculate_battery_usage_metrics,
    calculate_dispatch_metrics
)

def create_dispatch_performance_summary(
        dispatch_scenarios: dict[str, pd.DataFrame],
        market_data: pd.DataFrame,
        battery_parameters: dict[str, float],
        *,
        degradation_cost_per_kWh: float,
        timestep_hours: float = 0.25
) -> pd.DataFrame:
    """Summarize operational performance for every scenario."""

    if degradation_cost_per_kWh < 0:
        raise ValueError(
            "Degradation cost must not be negative."
        )

    if timestep_hours <= 0:
        raise ValueError(
            "Timestep hours must be positive."
        )

    expected_names = set(
        SCENARIO_OUTPUT_FILENAMES
    )

    if set(dispatch_scenarios) != expected_names:
        raise ValueError(
            "Dispatch scenario names do not match "
            "the required Week 4 scenarios."
        )

    required_market_columns = {
        "timestamp",
        "price_per_kWh",
        "gCO2/kWh",
    }

    missing_market_columns = (
        required_market_columns
        - set(market_data.columns)
    )

    if missing_market_columns:
        raise ValueError(
            "Maket data is missing columns: "
            f"{sorted(missing_market_columns)}"
        )

    market_signals = market_data[
        [
            "timestamp",
            "price_per_kWh",
            "gCO2/kWh",
        ]
    ].copy()

    summary_records = []

    for scenario_name, dispatch_data in (
        dispatch_scenarios.items()
    ):
        merged_data = dispatch_data.merge(
            market_signals,
            on="timestamp",
            how="inner",
            validate="one_to_one"
        )

        if len(merged_data) != len(dispatch_data):
            raise ValueError(
                f"{scenario_name} does not align with every market interval."
            )

        dispatch_metrics = calculate_dispatch_metrics(
            merged_data,
            timestep_hours=timestep_hours,     
        )

        battery_metrics = (
            calculate_battery_usage_metrics(
                merged_data,
                battery_parameters,
                timestep_hours=timestep_hours
            )
        )

        degradation_cost = (
            battery_metrics["throughput_kWh"]
            * degradation_cost_per_kWh
        )

        # In this model, to fully consider the impact of battery injection degradation
        # battery degradation cost is also calculated for total explicit cost
        summary_records.append(
            {
                "scenario": scenario_name,
                "grid_import_energy_kWh": (
                    dispatch_metrics["grid_import_kWh"]
                ),
                "energy_cost": (
                    dispatch_metrics["cost"]
                ),
                "emissions_kgCO2": (
                    dispatch_metrics["emissions_kgCO2"]
                ),
                "battery_charge_energy_kWh": (
                    battery_metrics["charge_kWh"]
                ),
                "battery_discharge_energy_kWh": (
                    battery_metrics["discharge_kWh"]
                ),
                "battery_throughput_kWh": (
                    battery_metrics["throughput_kWh"]
                ),
                "equivalent_full_cycles": (
                    battery_metrics["equivalent_full_cycles"]
                ),
                "degradation_cost": degradation_cost,
                "total_explicit_cost": (
                    dispatch_metrics["cost"]
                    + degradation_cost
                )
            }
        )

    return pd.DataFrame(summary_records)


def create_validation_report(
        dispatch_summary: pd.DataFrame,
        qsts_summary: pd.DataFrame,
) -> pd.DataFrame:
    """Combined operational and electrical scenario results."""

    if "scenario" not in dispatch_summary.columns:
        raise ValueError(
            "Dispatch summary must contain scenario."
        )

    if "scenario" not in qsts_summary.columns:
        raise ValueError(
            "QSTS summary must contain scenario."
        )

    expected_names = set(
        SCENARIO_OUTPUT_FILENAMES
    )

    dispatch_names = set(
        dispatch_summary["scenario"]
    )

    qsts_names = set(
        qsts_summary["scenario"]
    )

    if dispatch_names != expected_names:
        raise ValueError(
            "Dispatch summary does not contain all "
            "required Week 4 scenarios."
        )

    if qsts_names != expected_names:
        raise ValueError(
            "QSTS summary does not contain all "
            "required Week 4 scenarios."
        )

    renamed_dispatch_summary = (
        dispatch_summary.rename(
            columns={
                "grid_import_energy_kWh": (
                    "scheduled_grid_import_energy_kWh"
                ),
            }
        )
    )

    renamed_qsts_summary = (
        qsts_summary.rename(
            columns = {
                "grid_import_energy_kWh": (
                    "pcc_grid_import_energy_kWh"
                ),
                "grid_export_energy_kWh": (
                    "pcc_grid_export_energy_kWh"
                ),
            }
        )
    )

    validation_report = (
        renamed_dispatch_summary.merge(
            renamed_qsts_summary,
            on="scenario",
            how="inner",
            validate="one_to_one",
        )
    )

    return validation_report



# This function does not run an OpenDSS simulation.
# It reviews the completed Week 3-4 validation evidence and creates
# a machine-readable checklist showing whether the project is ready
# to pass Gate C and continue to Week 5. The validation_report contains
# calculated scenario results, while the two Boolean arguments confirm
# that the base feeder and solution-mode documentation were completed.
def build_validation_report(
        results_directory: Path,
        battery_parameters: dict[str, float],
        *,
        degradation_cost_per_kWh: float,
        timestep_hours: float = 0.25,
) -> pd.DataFrame:
    """Build the final report from saved Week 4 artifacts."""

    market_data_path = (
        results_directory
        / "week4_real_market_inputs_15min.csv"
    )

    qsts_summary_path = (
        results_directory
        / "week4_qsts_scenario_comparison.csv"
    )

    if not market_data_path.is_file():
        raise FileNotFoundError(
            f"Market input was not found: {market_data_path}"
        )

    if not qsts_summary_path.is_file():
        raise FileNotFoundError(
            f"QSTS summary was not found: {qsts_summary_path}"
        )

    dispatch_scenarios = (
        load_required_dispatch_scenarios(
            results_directory
        )
    )

    market_data = pd.read_csv(
        market_data_path,
        parse_dates=["timestamp"],
    )

    qsts_summary = pd.read_csv(
        qsts_summary_path
    )

    dispatch_summary = (
        create_dispatch_performance_summary(
            dispatch_scenarios,
            market_data,
            battery_parameters,
            degradation_cost_per_kWh=degradation_cost_per_kWh,
            timestep_hours=timestep_hours,
        )
    )

    return create_validation_report(
        dispatch_summary,
        qsts_summary,
    )


def create_opendss_validation_checklist(
        validation_report: pd.DataFrame,
        *,
        base_feeder_validated: bool,
        solution_modes_documented: bool,
) -> pd.DataFrame:
    """Evaluate the OpenDSS requirements for Gate C."""

    required_columns = {
        "scenario",
        "interval_count",
        "converged_intervals",
        "feasible_intervals",
        "minimum_voltage_pu",
        "maximum_voltage_pu",
        "maximum_line_loading_percent",
        "maximum_transformer_loading_percent",
        "feeder_loss_energy_kWh",
        "transformer_loss_energy_kWh",
        "reverse_power_flow_intervals",
        "voltage_violation_intervals",
        "line_overload_intervals",
        "transformer_overload_intervals",
    }

    missing_columns = (
        required_columns - set(validation_report.columns)
    )

    if missing_columns:
        raise ValueError(
            "Validation report is missing columns: "
            f"{sorted(missing_columns)}"
        )

    expected_names = set(
        SCENARIO_OUTPUT_FILENAMES
    )

    all_scenarios_replayed = (
        set(validation_report["scenario"])
        == expected_names
    )

    all_intervals_converged = bool(
        (
            validation_report[
                "converged_intervals"
            ]
            ==validation_report["interval_count"]
        ).all()
    )

    feasibility_accounted_for = bool(
        (validation_report["feasible_intervals"] >= 0).all()
        and
        (
            validation_report["feasible_intervals"]
            <= validation_report["interval_count"]
         ).all()
    )

    total_intervals = int(validation_report["interval_count"].sum())

    total_converged = int(validation_report["converged_intervals"].sum())

    infeasible_intervals = int(
        (
            validation_report["interval_count"]
            - validation_report["feasible_intervals"]
        ).sum()
    )

    reverse_flow_intervals = int(
        validation_report["reverse_power_flow_intervals"].sum()
    )

    checklist_records = [
        {
            "requirement": "Base feeder validated",
            "passed": base_feeder_validated,
            "evidence": (
                "Week 3 base-feeder test and recap"
            ),
        },

        {
            "requirement": (
                "All required scenarios replayed"
            ),
            "passed": all_scenarios_replayed,
            "evidence": (
                f"{len(validation_report)} scenarios, {total_intervals} intervals"
            ),
        },

        {
            "requirement": (
                "All interval solutions converged"
            ),
            "passed": all_intervals_converged,
            "evidence": (
                f"{total_converged} of {total_intervals} converged"
            ),
        },

        {
            "requirement": "Voltage results reported",
            "passed": True,
            "evidence": (
                "Minimum and maximum voltage columns"
            ),
        },

        {
            "requirement": (
                "Line and transformer loading reported"
            ),
            "passed": True,
            "evidence": (
                "Maximum equipment-loading columns"
            ),
        },

        {
            "requirement": "Electrical losses reported",
            "passed": True,
            "evidence": (
                "Feeder and transformer loss energy"
            ),
        },

        {
            "requirement": "Reverse power flow reported",
            "passed": True,
            "evidence": (
                f"{reverse_flow_intervals} reverse-flow "
                "intervals identified"
            ),
        },

        {
            "requirement": "Infeasible intervals identified",
            "passed": feasibility_accounted_for,
            "evidence": f"{infeasible_intervals} infeasible intervals identified",
        },

        {
            "requirement": "Machine-readable feasibility produced",
            "passed": feasibility_accounted_for,
            "evidence": "Feasibility and violation-count fields"
        },

        {
            "requirement": "OpenDSS solution modes documented",
            "passed": solution_modes_documented,
            "evidence": "Week 3 solution-mode document"
        },
    ]

    return pd.DataFrame(checklist_records)


def save_validation_artifacts(
        validation_report: pd.DataFrame,
        validation_checklist: pd.DataFrame,
        output_directory: Path,
) -> tuple[Path, Path]:
    """Save the final Week 4 validation artifacts."""

    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        output_directory
        / "week4_final_validation_report.csv"
    )

    checklist_path = (
        output_directory
        / "week4_opendss_validation_checklist.csv"
    )

    validation_report.to_csv(
        report_path,
        index=False,
    )

    validation_checklist.to_csv(
        checklist_path,
        index=False,
    )

    return report_path, checklist_path


def main() -> None:
    """Build, check, and save the final Week 4 report."""

    project_root = (
        Path(__file__).resolve().parents[2]
    )

    results_directory = (
        project_root / "results"
    )

    battery = Battery(
        capacity_kWh=20.0,
        SOC_min=0.1,
        SOC_max=0.9,
        energy_kWh=10.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        max_charge_kw=5.0,
        max_discharge_kw=5.0,
    )

    battery_parameters = (
        to_optimizer_parameters(
            battery
        )
    )

    validation_report = (
        build_validation_report(
            results_directory,
            battery_parameters,
            degradation_cost_per_kWh = 0.03,
            timestep_hours = 0.25,
        )
    )

    validation_checklist = (
        create_opendss_validation_checklist(
            validation_report,
            # Supported by the Week 3 tests and recap
            base_feeder_validated=True,
            # Supported by the week 3 solution-mode document.
            solution_modes_documented=True,
        )
    )

    report_path, checklist_path = (
        save_validation_artifacts(
            validation_report,
            validation_checklist,
            results_directory,
        )
    )

    print(
        "\n=== OpenDSS Validation Checklist ==="
    )

    print(
        validation_checklist.to_string(
            index=False
        )
    )

    print(
        "\nAll requirements passed: "
        f"{bool(validation_checklist['passed'].all())}"
    )

    print(
        f"Saved validation report: {report_path}"
    )

    print(
        f"Saved validation checklist: {checklist_path}"
    )


if __name__ == "__main__":
    main()
