"""Connect guided-interface requests to the time-series analysis backend."""

from dataclasses import dataclass
from datetime import date, timedelta
import math
import os
from pathlib import Path
from typing import Callable

import pandas as pd
from dotenv import find_dotenv, load_dotenv

from ..analysis.carbon_weights import build_scenario_name
from ..signal_pipeline.horizon import AnalysisHorizon, build_horizon
from ..signal_pipeline.price_sources import (
    CSVPrice,
    FixedRetailPrice,
    PriceSource,
)
from ..signal_pipeline.signal_loader import load_signal_data
from ..signal_pipeline.source_config import resolve_live_api_config
from ..signal_pipeline.region_config import get_region_config
from .model_specifications import MicrogridSpecification
from .time_series_analysis import (
    TimeSeriesAnalysisResult,
    run_microgrid_timeseries_analysis,
)

DEFAULT_SIGNAL_CACHE_DIRECTORY = (
    Path(__file__).resolve().parents[2]
    / ".cache"
    / "signal_data"
)


@dataclass
class InterfaceAnalysisResult:
    """Store display results and detailed backend results by carbon weight."""

    comparison: pd.DataFrame
    runs_by_carbon_weight: dict[float, TimeSeriesAnalysisResult]


def build_analysis_details(
    *,
    source_mode: str,
    region_id: str,
    market_location: str,
    csv_path: str,
    start_date: str,
    end_date_inclusive: str,
    timestep_minutes: int,
) -> tuple[tuple[str, str], ...]:
    """Build concise study metadata for display above the result table."""

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date_inclusive)

    if end < start:
        raise ValueError("Inclusive end date must not precede the start date.")

    if source_mode == "live_api":
        region = get_region_config(region_id)
        location = f"{region.description} ({market_location})"
        data_source = "Live APIs"
    else:
        filename = Path(csv_path).name or "Integrated CSV"
        location = f"Not applicable — integrated CSV: {filename}"
        data_source = "Integrated CSV"

    return (
        ("Data source", data_source),
        ("Location", location),
        (
            "Time range",
            f"{start.isoformat()} → {end.isoformat()} (both dates included)",
        ),
        ("Time interval", f"{timestep_minutes} minutes"),
    )


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
    progress_callback: Callable[[str], None] | None = None,
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

    if progress_callback is not None:
        progress_callback("Loading and validating the integrated signal CSV")

    signal_data = pd.read_csv(path)
    start = date.fromisoformat(start_date)
    end = start + timedelta(days=number_of_days)

    weights_to_run = (
        carbon_weights
        if "combined_optimal" in selected_scenarios
        else (carbon_weights[0],)
    )

    return _run_selected_signal_analysis(
        specification,
        signal_data,
        start_date=start_date,
        end_date=end.isoformat(),
        timestep_minutes=timestep_minutes,
        expected_timezone=expected_timezone,
        selected_scenarios=selected_scenarios,
        carbon_weights=weights_to_run,
        degradation_cost_per_kWh=degradation_cost_per_kWh,
        progress_callback=progress_callback,
    )


def run_live_api_analysis(
    specification: MicrogridSpecification,
    *,
    start_date: str,
    number_of_days: int,
    timestep_minutes: int,
    region_id: str,
    market_provider: str | None,
    market_location: str | None,
    carbon_provider: str | None,
    carbon_zone: str | None,
    timezone: str | None,
    price_mode: str,
    fixed_retail_price: float | None,
    price_csv_path: str | Path | None,
    selected_scenarios: tuple[str, ...],
    carbon_weights: tuple[float, ...],
    degradation_cost_per_kWh: float,
    progress_callback: Callable[[str], None] | None = None,
) -> InterfaceAnalysisResult:
    """Retrieve live regional signals and run the selected study scenarios."""

    if progress_callback is not None:
        progress_callback("Resolving regional market and carbon data sources")

    config = resolve_live_api_config(
        region_id,
        market_provider=market_provider,
        market_location=market_location,
        carbon_provider=carbon_provider,
        carbon_zone=carbon_zone,
        timezone=timezone,
    )
    horizon = build_horizon(
        start_date,
        number_of_days,
        config.timezone,
        timestep_minutes,
    )
    site_profile = create_temporary_site_profile(
        horizon,
        load_kw=specification.load_kw,
        pv_capacity_kw=specification.pv_capacity_kw,
    )
    price_source = _build_live_price_source(
        price_mode,
        horizon,
        fixed_retail_price=fixed_retail_price,
        price_csv_path=price_csv_path,
    )

    load_dotenv(find_dotenv(), override=False)
    carbon_api_key = os.getenv("ELECTRICITY_MAPS_API_KEY")

    if progress_callback is not None:
        progress_callback("Loading cached signals or retrieving provider data")

    signal_data = load_signal_data(
        config,
        horizon,
        site_profile=site_profile,
        price_source=price_source,
        carbon_api_key=carbon_api_key,
        cache_directory=DEFAULT_SIGNAL_CACHE_DIRECTORY,
    )

    weights_to_run = (
        carbon_weights
        if "combined_optimal" in selected_scenarios
        else (carbon_weights[0],)
    )

    return _run_selected_signal_analysis(
        specification,
        signal_data,
        start_date=horizon.start.isoformat(),
        end_date=horizon.end.isoformat(),
        timestep_minutes=timestep_minutes,
        expected_timezone=config.timezone,
        selected_scenarios=selected_scenarios,
        carbon_weights=weights_to_run,
        degradation_cost_per_kWh=degradation_cost_per_kWh,
        progress_callback=progress_callback,
    )


def create_temporary_site_profile(
    horizon: AnalysisHorizon,
    *,
    load_kw: float,
    pv_capacity_kw: float,
) -> pd.DataFrame:
    """Create constant load and a simplified daylight PV curve."""

    if load_kw < 0:
        raise ValueError("Temporary profile load must not be negative.")

    if pv_capacity_kw <= 0:
        raise ValueError("Temporary profile PV capacity must be positive.")

    pv_values = []

    for timestamp in horizon.index:
        hour = timestamp.hour + timestamp.minute / 60

        if 6 <= hour < 18:
            solar_fraction = math.sin(math.pi * (hour - 6) / 12)
            pv_output_kw = pv_capacity_kw * solar_fraction
        else:
            pv_output_kw = 0.0

        pv_values.append(max(pv_output_kw, 0.0))

    return pd.DataFrame(
        {
            "timestamp": horizon.index,
            "load_kw": load_kw,
            "pv_kw": pv_values,
        }
    )


def _build_live_price_source(
    price_mode: str,
    horizon: AnalysisHorizon,
    *,
    fixed_retail_price: float | None,
    price_csv_path: str | Path | None,
) -> PriceSource | None:
    """Build an optional price override for a live regional analysis."""

    if price_mode == "wholesale_market":
        return None

    if price_mode == "fixed_retail":
        return FixedRetailPrice(fixed_retail_price)

    if price_mode == "csv":
        if not price_csv_path:
            raise ValueError("Select a price CSV file.")

        path = Path(price_csv_path)

        if not path.is_file():
            raise FileNotFoundError(f"Price CSV was not found: {path}")

        price_data = pd.read_csv(path)

        if "timestamp" not in price_data.columns:
            raise ValueError("Price CSV is missing timestamp.")

        timestamps = pd.to_datetime(price_data["timestamp"], errors="raise")
        price_data["timestamp"] = (
            timestamps.dt.tz_localize(horizon.timezone)
            if timestamps.dt.tz is None
            else timestamps.dt.tz_convert(horizon.timezone)
        )

        return CSVPrice(price_data)

    if price_mode == "time_of_use":
        raise ValueError(
            "The time-of-use tariff editor is not connected yet. "
            "Choose wholesale, fixed retail, or CSV pricing for this test."
        )

    raise ValueError(f"Unsupported electricity price mode: {price_mode}.")


def _run_selected_signal_analysis(
    specification: MicrogridSpecification,
    signal_data: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    timestep_minutes: int,
    expected_timezone: str,
    selected_scenarios: tuple[str, ...],
    carbon_weights: tuple[float, ...],
    degradation_cost_per_kWh: float,
    progress_callback: Callable[[str], None] | None,
) -> InterfaceAnalysisResult:
    """Run backend scenarios and prepare the comparison selected by the GUI."""

    runs: dict[float, TimeSeriesAnalysisResult] = {}

    for run_index, weight in enumerate(carbon_weights):
        scenarios_for_run = (
            selected_scenarios
            if run_index == 0
            else ("combined_optimal",)
        )
        progress_prefix = (
            f"Analysis set {run_index + 1} of {len(carbon_weights)} "
            f"(carbon weight {weight:g})"
        )

        if progress_callback is not None:
            progress_callback(f"{progress_prefix}: preparing inputs")

        def report_stage(message: str) -> None:
            if progress_callback is not None:
                progress_callback(f"{progress_prefix}: {message}")

        runs[weight] = run_microgrid_timeseries_analysis(
            specification,
            signal_data,
            timestep_minutes=timestep_minutes,
            carbon_weight=weight,
            degradation_cost_per_kWh=degradation_cost_per_kWh,
            expected_timezone=expected_timezone,
            start_time=start_date,
            end_time=end_date,
            scenario_names=scenarios_for_run,
            progress_callback=report_stage,
        )

    first_weight = carbon_weights[0]
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

    analysis_days = (
        pd.Timestamp(end_date).date()
        - pd.Timestamp(start_date).date()
    ).days

    if analysis_days <= 0:
        raise ValueError("Analysis must include at least one calendar day.")

    comparison["average_daily_efc"] = (
        comparison["equivalent_full_cycles"]
        / analysis_days
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


RESULT_TABLE_COLUMNS = (
    ("scenario", "Scenario"),
    ("energy_cost", "Energy cost ($)"),
    ("degradation_cost", "Degradation ($)"),
    ("average_daily_efc", "Avg daily EFC"),
    ("total_explicit_cost", "Total cost ($)"),
    ("emissions_kgCO2", "Emissions (kgCO2)"),
    ("pcc_grid_import_energy_kWh", "Grid import (kWh)"),
    ("peak_grid_import_kw", "Peak import (kW)"),
    ("minimum_voltage_pu", "Min voltage (pu)"),
    ("maximum_line_loading_percent", "Max line (%)"),
    (
        "maximum_transformer_loading_percent",
        "Max transformer (%)",
    ),
)


def build_results_table(
    comparison: pd.DataFrame,
) -> tuple[tuple[str, ...], list[tuple[str, ...]]]:
    """Convert a comparison frame into user-facing table headings and rows."""

    headings = tuple(label for _, label in RESULT_TABLE_COLUMNS)
    rows: list[tuple[str, ...]] = []

    for _, result in comparison.iterrows():
        row_values = []

        for column, _label in RESULT_TABLE_COLUMNS:
            if column == "scenario":
                value = str(result[column])
            else:
                value = f"{float(result[column]):.2f}"

            row_values.append(value)

        rows.append(tuple(row_values))

    return headings, rows
