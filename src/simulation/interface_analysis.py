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
from ..billing import (
    calculate_billing,
    get_tariff,
    master_with_submeters_topology,
    single_pcc_topology,
)
from ..profiles import (
    BuildingArchetype,
    ConstantLoad,
    LoadScaling,
    SyntheticLoad,
    SyntheticPV,
)
from ..signal_pipeline.horizon import AnalysisHorizon, build_horizon
from ..signal_pipeline.price_sources import (
    CSVPrice,
    FixedRetailPrice,
    PriceSource,
)
from ..signal_pipeline.signal_loader import load_signal_data
from ..signal_pipeline.source_config import resolve_live_api_config
from ..signal_pipeline.region_config import get_region_config
from ..timeseries import build_interval_index_from_days
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
    warnings: tuple[str, ...] = ()


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
    load_profile_mode: str = "constant",
    load_archetype: str = "multifamily",
    load_variability_fraction: float = 0.0,
    tariff_id: str | None = None,
    meter_topology_mode: str = "single_pcc",
    submeter_count: int = 1,
    previous_peak_kw: float | None = None,
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
    site_profile = create_site_profile(
        horizon,
        load_kw=specification.load_kw,
        pv_capacity_kw=specification.pv_capacity_kw,
        load_profile_mode=load_profile_mode,
        load_archetype=load_archetype,
        load_variability_fraction=load_variability_fraction,
    )
    price_source = _build_live_price_source(
        price_mode,
        horizon,
        fixed_retail_price=fixed_retail_price,
        price_csv_path=price_csv_path,
        tariff_id=tariff_id,
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
        tariff_id=(tariff_id if price_mode == "time_of_use" else None),
        meter_topology_mode=meter_topology_mode,
        submeter_count=submeter_count,
        previous_peak_kw=previous_peak_kw,
        progress_callback=progress_callback,
    )


def create_temporary_site_profile(
    horizon: AnalysisHorizon,
    *,
    load_kw: float,
    pv_capacity_kw: float,
) -> pd.DataFrame:
    """Create the legacy constant-load, full-rating daylight profile."""

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


def create_site_profile(
    horizon: AnalysisHorizon,
    *,
    load_kw: float,
    pv_capacity_kw: float,
    load_profile_mode: str,
    load_archetype: str,
    load_variability_fraction: float,
) -> pd.DataFrame:
    """Build live-analysis load and available-PV inputs from GUI choices."""

    interval_index = build_interval_index_from_days(
        horizon.start.strftime("%Y-%m-%d"),
        horizon.number_of_days,
        horizon.timezone,
        horizon.timestep_minutes,
    )

    if load_profile_mode == "constant":
        load_source = ConstantLoad(load_kw)
    elif load_profile_mode == "synthetic":
        load_source = SyntheticLoad(
            archetype=BuildingArchetype(load_archetype),
            scaling=LoadScaling.PEAK_KW,
            peak_kw=load_kw,
            variability_fraction=load_variability_fraction,
        )
    else:
        raise ValueError(
            f"Unsupported load profile mode: {load_profile_mode}."
        )

    pv_source = SyntheticPV(
        rated_pv_capacity_kw=pv_capacity_kw,
    )

    load_values = load_source.build_load_kw(interval_index)
    pv_values = pv_source.build_pv_available_kw(interval_index)

    return pd.DataFrame(
        {
            "timestamp": horizon.index,
            "load_kw": load_values.to_numpy(dtype=float),
            "pv_kw": pv_values.to_numpy(dtype=float),
        }
    )


def _build_live_price_source(
    price_mode: str,
    horizon: AnalysisHorizon,
    *,
    fixed_retail_price: float | None,
    price_csv_path: str | Path | None,
    tariff_id: str | None = None,
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
        if not tariff_id:
            raise ValueError("Select a time-of-use tariff.")

        tariff = get_tariff(tariff_id, horizon.start.date())
        final_date = horizon.index[-1].date()
        if not tariff.is_effective_on(final_date):
            raise ValueError(
                f"Tariff {tariff_id} does not cover the complete analysis "
                f"through {final_date}."
            )

        tariff_prices = pd.DataFrame(
            {
                "timestamp": horizon.index,
                "price_per_kWh": tariff.energy_rates(
                    horizon.index
                ).to_numpy(dtype=float),
            }
        )
        return CSVPrice(tariff_prices)

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
    tariff_id: str | None = None,
    meter_topology_mode: str = "single_pcc",
    submeter_count: int = 1,
    previous_peak_kw: float | None = None,
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
            demand_charge_rate_per_kw=(
                _maximum_demand_rate(tariff_id)
                if tariff_id is not None
                else 0.0
            ),
            previous_peak_kw=previous_peak_kw,
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

    billing_warnings: list[str] = []
    if tariff_id is not None:
        comparison, billing_warnings = _apply_tariff_billing(
            comparison,
            runs,
            first_weight=first_weight,
            tariff_id=tariff_id,
            meter_topology_mode=meter_topology_mode,
            submeter_count=submeter_count,
            previous_peak_kw=previous_peak_kw,
            timestep_hours=timestep_minutes / 60.0,
        )

    if "carbon_weight" not in comparison.columns:
        comparison["carbon_weight"] = first_weight
    else:
        comparison["carbon_weight"] = comparison["carbon_weight"].fillna(
            first_weight
        )

    comparison["monetized_carbon_cost"] = (
        comparison["carbon_weight"]
        * comparison["emissions_kgCO2"]
    )
    comparison["carbon_adjusted_operating_cost"] = (
        comparison["total_explicit_cost"]
        + comparison["monetized_carbon_cost"]
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
        warnings=tuple(dict.fromkeys(billing_warnings)),
    )


def _apply_tariff_billing(
    comparison: pd.DataFrame,
    runs: dict[float, TimeSeriesAnalysisResult],
    *,
    first_weight: float,
    tariff_id: str,
    meter_topology_mode: str,
    submeter_count: int,
    previous_peak_kw: float | None,
    timestep_hours: float,
) -> tuple[pd.DataFrame, list[str]]:
    """Add complete tariff bill components to every displayed scenario."""

    tariff = get_tariff(tariff_id)
    if meter_topology_mode == "single_pcc":
        topology = single_pcc_topology(tariff_id)
    elif meter_topology_mode == "master_with_submeters":
        topology = master_with_submeters_topology(
            tariff_id,
            submeter_count,
        )
    else:
        raise ValueError(
            f"Unsupported GUI meter topology: {meter_topology_mode}."
        )

    billed = comparison.copy()
    warnings: list[str] = []

    for row_index, row in billed.iterrows():
        display_name = str(row["scenario"])
        if display_name.startswith("combined_optimal_"):
            run_weight = float(row["carbon_weight"])
            dispatch_name = "combined_optimal"
        else:
            run_weight = first_weight
            dispatch_name = display_name

        dispatch = runs[run_weight].dispatch_scenarios[dispatch_name]
        billing = calculate_billing(
            dispatch,
            topology,
            {tariff_id: tariff},
            timestep_hours=timestep_hours,
            previous_peak_kw=previous_peak_kw,
            battery_degradation_cost=float(row["degradation_cost"]),
        )

        billed.loc[row_index, "customer_charge"] = billing.customer_charge
        billed.loc[row_index, "energy_cost"] = billing.import_energy_charge
        billed.loc[row_index, "demand_charge"] = billing.demand_charge
        billed.loc[row_index, "export_credit"] = billing.export_credit
        billed.loc[row_index, "total_utility_charge"] = (
            billing.total_utility_charge
        )
        billed.loc[row_index, "total_explicit_cost"] = (
            billing.total_explicit_operating_cost
        )
        billed.loc[row_index, "billed_peak_kw"] = max(
            (period.billed_peak_kw for period in billing.periods),
            default=0.0,
        )
        warnings.extend(billing.warnings)
        for period in billing.periods:
            warnings.extend(period.warnings)

    return billed, warnings


def _maximum_demand_rate(tariff_id: str) -> float:
    """Return the tariff's combined maximum-demand rate in $/kW."""

    tariff = get_tariff(tariff_id)
    return sum(
        component.rate_per_kW
        for component in tariff.demand_charges
        if component.basis.value == "maximum"
    )


def format_comparison_for_display(comparison: pd.DataFrame) -> str:
    """Format the most useful economic and electrical metrics as text."""

    columns = [
        "scenario",
        "energy_cost",
        "degradation_cost",
        "total_explicit_cost",
        "emissions_kgCO2",
        "carbon_adjusted_operating_cost",
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
    ("total_explicit_cost", "Total cost ($)"),
    ("energy_cost", "Energy cost ($)"),
    ("demand_charge", "Demand charge ($)"),
    ("customer_charge", "Customer charge ($)"),
    ("export_credit", "Export credit ($)"),
    ("degradation_cost", "Degradation ($)"),
    ("average_daily_efc", "Avg daily EFC"),
    ("emissions_kgCO2", "Emissions (kgCO2)"),
    ("carbon_adjusted_operating_cost", "Carbon-adjusted cost ($)"),
    ("pcc_grid_import_energy_kWh", "Grid import (kWh)"),
    ("peak_grid_import_kw", "Peak import (kW)"),
    ("billed_peak_kw", "Billed peak (kW)"),
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

    displayed_columns = tuple(
        (column, label)
        for column, label in RESULT_TABLE_COLUMNS
        if column in comparison.columns
    )
    headings = tuple(label for _, label in displayed_columns)
    rows: list[tuple[str, ...]] = []

    for _, result in comparison.iterrows():
        row_values = []

        for column, _label in displayed_columns:
            if column == "scenario":
                value = str(result[column])
            else:
                value = f"{float(result[column]):.2f}"

            row_values.append(value)

        rows.append(tuple(row_values))

    return headings, rows
