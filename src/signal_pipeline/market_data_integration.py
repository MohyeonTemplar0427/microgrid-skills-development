import json, math, os, time
import pandas as pd
import numpy as np
from ..dispatch import single_day_analysis as sda
from . import electricity_maps_data as emd
from . import gridstatus_data as gsd
from ..dispatch import multi_day_analysis as mda
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from ..dispatch.battery import Battery
from ..billing import calculate_flat_demand_charge
from ..dispatch.config import ExperimentConfig, to_optimizer_parameters
from ..dispatch.results import ExperimentResult
from .experiment_data import ExperimentData
from dataclasses import replace
from .timeseries_validation import merge_complete_time_series
from .region_config import RegionConfig, get_region_config
from ..opendss.opendss_handoff import create_opendss_handoff


def resolve_region_config(
    config: ExperimentConfig,
) -> RegionConfig:
    """Apply any per-field overrides on top of the named region's defaults."""

    return replace(
        get_region_config(config.region),
        market_location=config.market_location,
        carbon_zone=config.electricity_maps_zone,
        timezone=config.timezone,
    )


env_path = find_dotenv()

PROJECT_ROOT = (
    Path(__file__).resolve().parents[2]
)

RUNTIME_FILE = (
    PROJECT_ROOT
    / "data"
    / "runtime.json"
)

load_dotenv(
    env_path, 
    override=True,
)

api_key = os.getenv(
    "ELECTRICITY_MAPS_API_KEY"
)


def load_previous_runtime() -> float | None:
    if not RUNTIME_FILE.exists():
        return None

    with open(RUNTIME_FILE, "r") as file:
        data = json.load(file)

    return float(data["runtime"])


def save_runtime(runtime:float) -> None:
    RUNTIME_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(RUNTIME_FILE, "w") as file:
        json.dump(
            {"runtime": runtime},
            file,
            indent = 4
        )

#Merge real market data from sda,
def merge_real_market_data(
        synthetic_data: pd.DataFrame,
        price_data: pd.DataFrame,
        carbon_data: pd.DataFrame,
) -> pd.DataFrame:

    base_data = synthetic_data.drop(
        columns = [
            "price_per_kWh",
            "gCO2/kWh",
        ]
    )

    merged_data = merge_complete_time_series(
        base_data,
        price_data,
        right_name="Price",
    )

    merged_data = merge_complete_time_series(
        merged_data,
        carbon_data,
        right_name="Carbon"
    )

    return merged_data

def create_market_signal_scenarios(
    synthetic_data: pd.DataFrame,
    price_data: pd.DataFrame,
    carbon_data: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """
    Create scenarios that isolate real price and carbon signals.
    """

    synthetic_scenario = synthetic_data.copy()

    real_price_scenario = (
        merge_complete_time_series(
            synthetic_data.drop(
                columns=["price_per_kWh"]
            ),
            price_data,
            right_name="Price",
        )
    )

    real_carbon_scenario = (
        merge_complete_time_series(
            synthetic_data.drop(
                columns=["gCO2/kWh"]
            ),
            carbon_data,
            right_name="Carbon"
            )
        )
    combined_real_scenario = (
        merge_real_market_data(
            synthetic_data,
            price_data,
            carbon_data,
        )
    )

    return {
        "synthetic": synthetic_scenario,
        "real_price": real_price_scenario,
        "real_carbon": real_carbon_scenario,
        "combined_real": combined_real_scenario,
    }


def calculate_cost_with_external_price(
        dispatch_data: pd.DataFrame,
        price_data: pd.DataFrame,
        timestep_hours: float = 0.25,
) -> float:

    dispatch_intervals = dispatch_data[[
            "timestamp",
            "grid_import_kw",
            ]
        ].copy()


    merged_data = merge_complete_time_series(
        dispatch_intervals,
        price_data,
        right_name="Price",
    )
    cost = (
        merged_data["grid_import_kw"]
        * timestep_hours
        * merged_data["price_per_kWh"]
    ).sum()

    return float(cost)



def create_real_dispatch_summary(
        dispatch_data: pd.DataFrame,
        market_data: pd.DataFrame,
) -> pd.DataFrame:

    market_signals = market_data[
        [
            "timestamp",
            "price_per_kWh",
            "gCO2/kWh",
        ]
    ].copy()

    dispatch = dispatch_data[
        [
            "timestamp",
            "battery_charge_kw",
            "battery_discharge_kw",
        ]
    ].copy()

    summary = merge_complete_time_series(
        dispatch,
        market_signals,
        right_name = "Market signal"
    )

    return summary


## calculate the power-weighted average price and carbon intensity during charging and discharging
## value can be carbon intensity or unit electricity price

def calculate_power_weighted_average(
        data: pd.DataFrame,
        value_column: str,
        power_column: str,
) -> float:

    total_power = (
        data[power_column].sum()
    )

    if total_power <= 0:
        raise ValueError(
            "Total power must be greater than zero."
        )

    weighted_average = (
        (
            data[value_column]
            * data[power_column]
        ).sum()
        / total_power
    )

    return float(weighted_average)


def create_no_battery_dispatch(
        data: pd.DataFrame,
) -> pd.DataFrame:

    no_battery_data = data.copy()

    no_battery_data["grid_import_kw"] = (
        no_battery_data["net_load_kw"]
        .clip(lower=0)
    )

    no_battery_data["battery_charge_kw"] = 0.0
    no_battery_data["battery_discharge_kw"] = 0.0

    return no_battery_data


def validate_integrated_market_data(
    data: pd.DataFrame,
    expected_rows: int,
    timestep_minutes: int = 15,
    expected_timezone: str = "America/Los_Angeles",
) -> None:

    required_columns = {
        "timestamp",
        "load_kw",
        "pv_kw",
        "net_load_kw",
        "price_per_kWh",
        "gCO2/kWh",
    }

    missing_columns = (
        required_columns
        - set(data.columns)
    )

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    numeric_columns = [
        "load_kw",
        "pv_kw",
        "net_load_kw",
        "price_per_kWh",
        "gCO2/kWh",
    ]

    try:
        numeric_data = data[
            numeric_columns
        ].apply(
            pd.to_numeric,
            errors="raise",
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Integrated market data contains "
            "nonnumeric values."
        ) from error

    if not np.isfinite(
        numeric_data.to_numpy(dtype=float)
    ).all():
        raise ValueError(
            "Integrated market data contains "
            "non-finite numeric values."
        )

    timestamps = data["timestamp"]

    if not pd.api.types.is_datetime64_any_dtype(
        timestamps
    ):
        raise ValueError("Timestamp column must use a pandas datetime dtype.")

    if timestamps.dt.tz is None:
        raise ValueError(
            "Timestamps must be timezone-aware."
        )

    if str(timestamps.dt.tz) != expected_timezone:
        raise ValueError(
            f"Expected timezone {expected_timezone}, "
            f"but received {timestamps.dt.tz}."
        )

    if len(data) != expected_rows:
        raise ValueError(
            f"Expected {expected_rows} rows, "
            f"but received {len(data)}."
        )

    if data.isna().any().any():
        raise ValueError(
            "Integrated market data contains missing values."
        )

    if not data["timestamp"].is_unique:
        raise ValueError(
            "Duplicate timestamps found."
        )

    if not data[
        "timestamp"
    ].is_monotonic_increasing:
        raise ValueError(
            "Timestamps are not increasing."
        )

    time_differences = (
        data["timestamp"]
        .diff()
        .dropna()
    )

    expected_timestep = pd.Timedelta(
        minutes=timestep_minutes
    )

    if not (
        time_differences
        == expected_timestep
    ).all():
        raise ValueError(
            "Integrated data does not have "
            "continuous 15-minute intervals."
        )

    if (
        data["gCO2/kWh"] < 0
    ).any():
        raise ValueError(
            "Carbon intensity cannot be negative."
        )

##Running multi-day experiment with input parameters
def run_multi_day_experiment(
        config: ExperimentConfig,
        data: ExperimentData,
        battery_parameters: dict[str, float],
) -> ExperimentResult:

    synthetic_data = data.synthetic_data
    price_data = data.price_data
    carbon_data = data.carbon_data
    real_market_data = data.real_market_data

    # 3. Run optimization
    scenarios = create_market_signal_scenarios(
        synthetic_data,
        price_data,
        carbon_data,
    )

    optimized_scenarios = {
        scenario_name: sda.run_combined_optimization(
            scenario_data,
            battery_parameters,
            carbon_weight = config.carbon_weight,
            degradation_cost_per_kWh = config.degradation_cost_per_kWh,
            demand_charge_rate_per_kw = config.demand_charge_rate_per_kw,
            previous_peak_kw = config.previous_peak_kw,
        )
        for scenario_name, scenario_data
        in scenarios.items()
    }

    synthetic_optimized = (
        optimized_scenarios["synthetic"]
    )

    real_price_optimized = (
        optimized_scenarios["real_price"]
    )

    real_carbon_optimized = (
        optimized_scenarios["real_carbon"]
    )

    real_market_optimized = (
        optimized_scenarios["combined_real"]
    )
    #4. Validate Optimized Dispatch
    for scenario_name, optimized_data in (
        optimized_scenarios.items()
    ):
        try:
            sda.validate_dispatch(
                optimized_data,
                battery_parameters,
            )
        except ValueError as error:
            raise ValueError(
                f"Dispatch validation failed for {scenario_name}"
            ) from error

    opendss_handoff = create_opendss_handoff(
        real_market_optimized,
        timestep_minutes=int(
            config.timestep_hours * 60
        ),
        expected_timezone=config.timezone,
    )


    scenario_metrics: dict[
        str,
        dict[str, float],
    ] = {}

    for (
        scenario_name,
        optimized_data,
    ) in optimized_scenarios.items():

        evaluated_cost =(
            calculate_cost_with_external_price(
                optimized_data,
                price_data,
                timestep_hours=config.timestep_hours,
            )
        )

        evaluated_emissions = (
            emd.calculate_emissions_with_external_carbon(
                optimized_data,
                carbon_data,
                timestep_hours=config.timestep_hours,
            )
        )

        battery_usage = (
            sda.calculate_battery_usage_metrics(
                optimized_data,
                battery_parameters,
                timestep_hours=config.timestep_hours,
            )
        )

        battery_throughput = float(
            battery_usage['throughput_kWh']
        )

        degradation_cost = (
            battery_throughput
            * config.degradation_cost_per_kWh
        )

        demand_charge_cost = (
            calculate_flat_demand_charge(
                optimized_data,
                config.demand_charge_rate_per_kw,
                previous_peak_kw=config.previous_peak_kw,
            )
        )

        scenario_metrics[scenario_name] = {
            "cost": float(evaluated_cost),
            "emissions_kgCO2": float(
                evaluated_emissions
            ),
            "battery_throughput_kWh": (
                battery_throughput
            ),
            "degradation_cost": float(
                degradation_cost
            ),
            "demand_charge_cost": float(
                demand_charge_cost
            ),
            "total_operating_cost": float(
                evaluated_cost
                + degradation_cost
                + demand_charge_cost
            ),
        }



    #5. No-battery baseline

    no_battery_dispatch = (
        create_no_battery_dispatch(
            real_market_data,
        )
    )

    #6. Evaluate cost using Real CAISO Prices

    no_battery_cost = (
        calculate_cost_with_external_price(
            no_battery_dispatch,
            price_data,
            timestep_hours=config.timestep_hours
        )
    )

    no_battery_demand_charge_cost = (
        calculate_flat_demand_charge(
            no_battery_dispatch,
            config.demand_charge_rate_per_kw,
            previous_peak_kw=config.previous_peak_kw,
        )
    )

    synthetic_real_cost = (
        calculate_cost_with_external_price(
            synthetic_optimized,
            price_data,
            timestep_hours=config.timestep_hours
        )
    )

    real_market_cost = (
        calculate_cost_with_external_price(
            real_market_optimized,
            price_data,
            timestep_hours=config.timestep_hours,
        )
    )

    #7. Evaluate emissions using Real carbon data

    no_battery_emissions = (
        emd.calculate_emissions_with_external_carbon(
            no_battery_dispatch,
            carbon_data,
        )
    )

    synthetic_real_emissions = (
        emd.calculate_emissions_with_external_carbon(
            synthetic_optimized,
            carbon_data,
        )
    )

    real_market_emissions = (
        emd.calculate_emissions_with_external_carbon(
            real_market_optimized,
            carbon_data,
        )
    )

    scenario_metrics["no_battery"] = {
        "cost": float(no_battery_cost),
        "emissions_kgCO2": float(
            no_battery_emissions
        ),
        "battery_throughput_kWh": 0.0,
        "degradation_cost": 0.0,
        "demand_charge_cost": float(
            no_battery_demand_charge_cost
        ),
        "total_operating_cost": float(
            no_battery_cost
            + no_battery_demand_charge_cost
        ),
    }

    # 8. Battery Usage

    synthetic_usage = (
        sda.calculate_battery_usage_metrics(
            synthetic_optimized,
            battery_parameters,
            timestep_hours = config.timestep_hours
        )
    )

    real_market_usage = (
        sda.calculate_battery_usage_metrics(
            real_market_optimized,
            battery_parameters,
            timestep_hours = config.timestep_hours,
        )
    )

    real_market_degradation_cost = (
        real_market_usage["throughput_kWh"]
        * config.degradation_cost_per_kWh
    )

    real_market_demand_charge_cost = (
        calculate_flat_demand_charge(
            real_market_optimized,
            config.demand_charge_rate_per_kw,
            previous_peak_kw=config.previous_peak_kw,
        )
    )

    real_market_total_operating_cost = (
        real_market_cost
        + real_market_degradation_cost
        + real_market_demand_charge_cost
    )

    #9. Analyze real-market dispatch
    dispatch_summary = (
        create_real_dispatch_summary(
            real_market_optimized,
            real_market_data,
        )
    )

    active_charging = (
        dispatch_summary.loc[
            dispatch_summary[
                "battery_charge_kw"
            ] > 0.01
        ].copy()
    )

    active_discharging = (
        dispatch_summary.loc[
            dispatch_summary[
                "battery_discharge_kw"
            ] > 0.01
        ].copy()
    )

    weighted_charge_price = (
        calculate_power_weighted_average(
            active_charging,
            "price_per_kWh",
            "battery_charge_kw",
        )
    )

    weighted_discharge_price =(
        calculate_power_weighted_average(
            active_discharging,
            "price_per_kWh",
            "battery_discharge_kw"
        )
    )

    weighted_charge_carbon = (
        calculate_power_weighted_average(
            active_charging,
            "gCO2/kWh",
            "battery_charge_kw",
        )
    )

    weighted_discharge_carbon = (
        calculate_power_weighted_average(
            active_discharging,
            "gCO2/kWh",
            "battery_discharge_kw",
        )
    )

    # 10. Improvements vs no battery
    cost_savings = (
        no_battery_cost
        - real_market_cost
    )

    operating_cost_savings = (
        (no_battery_cost + no_battery_demand_charge_cost)
        - real_market_total_operating_cost
    )

    emissions_reduction = (
        no_battery_emissions
        - real_market_emissions
    )

    daily_summary = calculate_daily_metrics(
        data=real_market_optimized,
        degradation_cost_per_kWh=(
            config.degradation_cost_per_kWh
        ),
        timestep_hours=config.timestep_hours,
    )


    return ExperimentResult(
        no_battery_cost=float(
            no_battery_cost
        ),

        no_battery_emissions=float(
            no_battery_emissions
        ),

        synthetic_real_cost=float(
            synthetic_real_cost
        ),

        synthetic_real_emissions=float(
            synthetic_real_emissions
        ),

        real_market_cost=float(
            real_market_cost
        ),

        real_market_emissions=float(
            real_market_emissions
        ),

        cost_savings=float(
            cost_savings
        ),

        emissions_reduction=float(
            emissions_reduction
        ),

        synthetic_usage=synthetic_usage,
        real_market_usage=real_market_usage,

        weighted_charge_price=float(
            weighted_charge_price
        ),

        weighted_discharge_price = float(
            weighted_discharge_price
        ),

        weighted_charge_carbon = float(
            weighted_charge_carbon
        ),

        weighted_discharge_carbon = float(
            weighted_discharge_carbon
        ),

        real_market_degradation_cost = float(
            real_market_degradation_cost
        ),

        real_market_total_operating_cost = float(
            real_market_total_operating_cost
        ),

        operating_cost_savings = float(
            operating_cost_savings
        ),

        daily_summary = daily_summary,

        real_market_demand_charge_cost = float(
            real_market_demand_charge_cost
        ),

        no_battery_demand_charge_cost = float(
            no_battery_demand_charge_cost
        ),

        scenario_metrics=scenario_metrics,
        opendss_handoff=opendss_handoff,
    )

def prepare_experiment_data(
    config: ExperimentConfig,
    api_key: str,
) -> ExperimentData:

    synthetic_data = (
        mda.create_multi_day_dataframe(
            config.start_date,
            config.number_of_days,
        )
    )

    region_config = resolve_region_config(config)

    price_data = (
        gsd.fetch_region_prices(
            region_config,
            start_date=config.start_date,
            number_of_days=config.number_of_days,
            sleep_seconds=config.sleep_seconds,
        )
    )

    carbon_data = (
        emd.get_multi_day_carbon_data(
            api_key,
            config.electricity_maps_zone,
            config.start_date,
            config.number_of_days,
            timezone=config.timezone,
        )
    )

    real_market_data = (
        merge_real_market_data(
            synthetic_data,
            price_data,
            carbon_data,
        )
    )

    validate_integrated_market_data(
        real_market_data,
        expected_rows=len(price_data),
        timestep_minutes=int(config.timestep_hours * 60),
        expected_timezone=config.timezone,
    )

    return ExperimentData(
        synthetic_data = synthetic_data,
        price_data=price_data,
        carbon_data=carbon_data,
        real_market_data=real_market_data,
    )


def calculate_daily_metrics(
        data:pd.DataFrame,
        degradation_cost_per_kWh: float,
        timestep_hours: float = 0.25,
) -> pd.DataFrame:

    daily_data = data.copy()

    daily_data["date"] = (
        daily_data["timestamp"].dt.date
    )

    daily_data["grid_import_kWh"] = (
        daily_data["grid_import_kw"]
        * timestep_hours
    )

    daily_data["grid_cost"] = (
        daily_data["grid_import_kw"]
        * timestep_hours
        * daily_data["price_per_kWh"]
    )

    daily_data["emissions_kgCO2"] = (
        daily_data["grid_import_kw"]
        * timestep_hours
        * daily_data["gCO2/kWh"]
        / 1000
    )

    daily_data["battery_charge_kWh"] = (
        daily_data["battery_charge_kw"]
        * timestep_hours
    )

    daily_data["battery_discharge_kWh"] = (
        daily_data["battery_discharge_kw"]
        * timestep_hours
    )

    daily_summary = (
        daily_data
        .groupby("date")
        .agg(
            grid_import_kWh = (
                "grid_import_kWh",
                "sum",
            ),
            grid_cost = (
                "grid_cost",
                "sum",
            ),
            emissions_kgCO2=(
                "emissions_kgCO2",
                "sum",
            ),
            charge_kWh=(
                "battery_charge_kWh",
                "sum"
            ),
            discharge_kWh=(
                "battery_discharge_kWh",
                "sum",
            ),
        ).reset_index()
    )

    daily_summary["throughput_kWh"] = (
        daily_summary["charge_kWh"]
        + daily_summary["discharge_kWh"]
    )

    daily_summary["degradation_cost"] = (
        daily_summary["throughput_kWh"]
        * degradation_cost_per_kWh
    )

    return daily_summary


def calculate_normalized_kpis(
    result: ExperimentResult,
    number_of_days: int,
) -> dict[str, float]:

    cost_savings_percentage = (
        result.operating_cost_savings
        / result.no_battery_cost
        * 100
    )

    emissions_reduction_percentage = (
        result.emissions_reduction
        / result.no_battery_emissions
        * 100
    )

    average_daily_cost_savings = (
        result.operating_cost_savings
        / number_of_days
    )

    average_daily_emissions_reduction = (
        result.emissions_reduction
        / number_of_days
    )

    equivalent_full_cycles_per_day = (
        result.real_market_usage[
            "equivalent_full_cycles"
        ]
        / number_of_days
    )

    return {
        "cost_savings_percentage": cost_savings_percentage,
        "emissions_reduction_percentage": emissions_reduction_percentage,
        "average_daily_cost_savings": average_daily_cost_savings,
        "average_daily_emissions_reduction": average_daily_emissions_reduction,
        "equivalent_full_cycles_per_day": equivalent_full_cycles_per_day,
    }

def create_scenario_comparison_table(
        scenario_metrics: dict[
            str,
            dict[str, float],
        ],
) -> pd.DataFrame:
    """Create a common-baseline comparison for all signal scenarios"""

    if "no_battery" not in scenario_metrics:
        raise ValueError(
            "Scenario metrics must include a no_battery baseline."
        )

    comparison = (
        pd.DataFrame.from_dict(
            scenario_metrics,
            orient="index"
        )
        .rename_axis("scenario")
        .reset_index()
    )

    baseline = (
        comparison.loc[
            comparison["scenario"]
            == "no_battery"
        ]
        .iloc[0]
    )

    comparison["cost_savings"] = (
        baseline["cost"]
        - comparison["cost"]
    )

    comparison["operating_cost_savings"] = (
        baseline["total_operating_cost"]
        - comparison["total_operating_cost"]
    )

    comparison["emissions_reduction_kgCO2"] = (
        baseline["emissions_kgCO2"]
        - comparison["emissions_kgCO2"]
    )

    return comparison
    

def experiment_result_to_dict(
        experiment_name: str,
        carbon_weight: float,
        result: ExperimentResult,
        number_of_days: int,
) -> dict[str, float | str]:

    kpis = calculate_normalized_kpis(
        result = result,
        number_of_days=number_of_days,
    )

    return{
        "experiment_name": experiment_name,

        "carbon_weight": carbon_weight,

        "no_battery_cost": (
            result.no_battery_cost
        ),

        "real_market_cost": (
            result.real_market_cost
        ),

        "battery_throughput_kWh": (
            result.real_market_usage[
                "throughput_kWh"
            ]
        ),

        "degradation_cost": (
            result.real_market_degradation_cost
        ),

        "total_operating_cost": (
            result.real_market_total_operating_cost
        ),

        "operating_cost_savings": (
            result.operating_cost_savings
        ),

        "cost_savings_percentage": (
            kpis["cost_savings_percentage"]
        ),

        "real_market_emissions": (
            result.real_market_emissions
        ),

        "emissions_reduction": (
            result.emissions_reduction
        ),

        "emissions_reduction_percentage": (
            kpis["emissions_reduction_percentage"]
        ),

        "equivalent_full_cycles": (
            result.real_market_usage[
                "equivalent_full_cycles"
            ]
        ),

        "equivalent_full_cycles_per_day": (
            kpis[
                "equivalent_full_cycles_per_day"
            ]
        ),
    }

def calculate_sensitivity_metrics(
        comparison_table: pd.DataFrame,
) -> pd.DataFrame:

    analysis = (
        comparison_table
        .sort_values("carbon_weight")
        .copy()
    )

    analysis["change_in_operating_cost"] = (
        analysis["total_operating_cost"]
        .diff()
    )

    analysis["additional_emissions_reduction"] = (
        analysis["emissions_reduction"]
        .diff()
    )

    analysis["additional_throughput_kWh"] = (
        analysis["battery_throughput_kWh"]
        .diff()
    )

    analysis["additional_EFC"] = (
        analysis["equivalent_full_cycles"]
        .diff()
    )

    analysis["extra_throughput_per_kgCO2"] = (
        analysis["additional_throughput_kWh"]
        / analysis[
            "additional_emissions_reduction"
        ]
    )

    analysis["marginal_cost_per_kgCO2"] = (
        analysis["change_in_operating_cost"]
        / analysis[
            "additional_emissions_reduction"
        ]
    )

    return analysis


    
# Main--------------------------------------------------------------------------------------------
def main() -> None:

    if api_key is None:
        raise ValueError(
            "Electricity Maps API key not loaded."
        )

    # Battery configuration
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

    signal_scenario_tables = [] 

    # Experiment configuration
    base_config = ExperimentConfig(
        start_date="2026-08-25",
        number_of_days=2,
    )

    carbon_weights = [
        0.00,
        0.20,
        0.50,
    ]

    start_time = (
        time.perf_counter()
    )

    # Fetch market data once
    experiment_data = (
        prepare_experiment_data(
            config=base_config,
            api_key=api_key,
        )
    )

    # Carbon-weight sweep
    for carbon_weight in carbon_weights:

        current_config = replace(
            base_config,
            carbon_weight=carbon_weight,
        )

        result = run_multi_day_experiment(
            config=current_config,
            data=experiment_data,
            battery_parameters=battery_parameters,
        )

        if math.isclose(
            carbon_weight,
            base_config.carbon_weight,
        ):
            handoff_output_path = (
                PROJECT_ROOT
                / "results"
                / "week2_opendss_handoff_combined_real_15min.csv"
            )

            handoff_output_path.parent.mkdir(
                parents=True,
                exist_ok=True
            )

            result.opendss_handoff.to_csv(
                handoff_output_path,
                index=False,
            )

            handoff_metadata_path = (
                PROJECT_ROOT
                / "results"
                / "week2_opendss_handoff_combined_real_15min_metadata.json"
            )

            handoff_metadata = {
                "scenario": "combined_real",
                "carbon_weight": carbon_weight,
                "region": current_config.region,
                "market_provider": current_config.market_provider,
                "market_location": current_config.market_location,
                "carbon_zone": current_config.electricity_maps_zone,
                "timestep_minutes": int(
                    current_config.timestep_hours * 60
                ),
                "timezone": current_config.timezone,
                "rows": len(result.opendss_handoff),
                "zero_tolerance_kw": 1e-6,
                "units": {
                    "timestamp": (
                        f"ISO 8601 {current_config.timezone}"
                    ),
                    "load_kw": "kW",
                    "pv_kw": "kW",
                    "battery_charge_kw": "kW",
                    "battery_discharge_kw": "kW",
                    "grid_import_kw": "kW",
                    "grid_export_kw": "kW",
                    "battery_soc_kWh": "kWh",
                    "battery_net_injection_kw": "kW",
                    "grid_net_import_kw": "kW",
                },
                "sign_conventions": {
                    "battery_net_injection_kW": (
                        "Positive supplies the feeder; "
                        "negative consumes from the feeder."
                    ),
                    "grid_net_import_kw": (
                        "Positive imports from the utility;"
                        "negative exports to the utility."
                    )
                },
                "formulas": {
                    "battery_net_injection_kw": (
                        "battery_discharge_kw - battery_charge_kw"
                    ),
                    "grid_net_import_kw": (
                        "grid_import - grid_export_kw"
                    ),
                },
            }

            handoff_metadata_path.write_text(
                json.dumps(
                    handoff_metadata,
                    indent = 4,
                )
                + "\n",
                encoding = "utf-8"
            )

        signal_scenario_table = (
            create_scenario_comparison_table(
                result.scenario_metrics
            )
        )

        signal_scenario_table.insert(
            0,
            "carbon_weight",
            carbon_weight,
        )

        signal_scenario_tables.append(
            signal_scenario_table
        )

    signal_scenario_comparison = pd.concat(
        signal_scenario_tables,
        ignore_index = True,
    )

    scenario_output_path = (
        PROJECT_ROOT
        / "results"
        / "week2_market_signal_scenario_comparison.csv"
    )

    scenario_output_path.parent.mkdir(
        parents = True,
        exist_ok = True,
    )

    signal_scenario_comparison.to_csv(
        scenario_output_path,
        index=False,
    )

    # Runtime
    runtime = (
        time.perf_counter()
        - start_time
    )

    save_runtime(
        runtime
    )


if __name__ == "__main__":
    main()
