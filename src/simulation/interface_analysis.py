"""Connect guided-interface requests to the time-series analysis backend."""

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ..analysis.carbon_weights import build_scenario_name
from .model_specifications import MicrogridSpecification
from .time_series_analysis import (
    TimeSeriesAnalysisResult,
    run_microgrid_timeseries_analysis,
)


@dataclass
class InterfaceAnalysisResult:
    """Store display results and detailed backend results by carbon weight."""

    comparison: pd.DataFrame
    runs_by_carbon_weight: dict[float, TimeSeriesAnalysisResult]


def run_integrated_csv_analysis(
    specification: MicrogridSpecification,
    csv_path: str | Path,
    *,
    start_date: str,
    number_of_days: int,
    timestep_minutes: int,
    expected_timezone: str,
    selected_scenarios: tuple[str, ...],
    carbon_weights: tuple[float, ...],
    degradation_cost_per_kWh: float,
) -> InterfaceAnalysisResult:
    """Run selected scenarios using one integrated signal CSV file."""

    path = Path(csv_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"Integrated signal CSV was not found: {path}"
        )

    if number_of_days <= 0:
        raise ValueError("Number of days must be positive.")

    if not selected_scenarios:
        raise ValueError("Select at least one analysis scenario.")

    if "no_battery" not in selected_scenarios:
        raise ValueError("The no-battery baseline must remain selected.")

    if not carbon_weights:
        raise ValueError("Provide at least one carbon weight.")

    signal_data = pd.read_csv(path)
    start = date.fromisoformat(start_date)
    end = start + timedelta(days=number_of_days)

    weights_to_run = (
        carbon_weights
        if "combined_optimal" in selected_scenarios
        else (carbon_weights[0],)
    )

    runs: dict[float, TimeSeriesAnalysisResult] = {}

    for weight in weights_to_run:
        runs[weight] = run_microgrid_timeseries_analysis(
            specification,
            signal_data,
            timestep_minutes=timestep_minutes,
            carbon_weight=weight,
            degradation_cost_per_kWh=degradation_cost_per_kWh,
            expected_timezone=expected_timezone,
            start_time=start.isoformat(),
            end_time=end.isoformat(),
        )

    first_weight = weights_to_run[0]
    first_comparison = runs[first_weight].comparison
    comparison_parts: list[pd.DataFrame] = []

    ordinary_scenarios = tuple(
        scenario
        for scenario in selected_scenarios
        if scenario != "combined_optimal"
    )

    if ordinary_scenarios:
        ordinary = first_comparison.loc[
            first_comparison["scenario"].isin(ordinary_scenarios)
        ].copy()
        comparison_parts.append(ordinary)

    if "combined_optimal" in selected_scenarios:
        for weight, result in runs.items():
            combined = result.comparison.loc[
                result.comparison["scenario"] == "combined_optimal"
            ].copy()
            combined["scenario"] = build_scenario_name(
                "combined_optimal",
                weight,
            )
            combined["carbon_weight"] = weight
            comparison_parts.append(combined)

    comparison = pd.concat(
        comparison_parts,
        ignore_index=True,
    )

    return InterfaceAnalysisResult(
        comparison=comparison,
        runs_by_carbon_weight=runs,
    )


def format_comparison_for_display(comparison: pd.DataFrame) -> str:
    """Format the most useful economic and electrical metrics as text."""

    columns = [
        "scenario",
        "energy_cost",
        "degradation_cost",
        "total_explicit_cost",
        "emissions_kgCO2",
        "pcc_grid_import_energy_kWh",
        "peak_grid_import_kw",
        "minimum_voltage_pu",
        "maximum_line_loading_percent",
        "maximum_transformer_loading_percent",
        "feasible_intervals",
        "interval_count",
    ]
    available = [column for column in columns if column in comparison.columns]

    display = comparison[available].copy()

    numeric_columns = display.select_dtypes(include="number").columns
    display[numeric_columns] = display[numeric_columns].round(4)

    return display.to_string(index=False)
