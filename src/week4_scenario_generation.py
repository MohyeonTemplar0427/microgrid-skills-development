"""Generate the real-signal dispatch schedules required for Week 4."""

import os
from pathlib import Path

from dotenv import load_dotenv

from .battery import Battery
from .config import(
    ExperimentConfig,
    to_optimizer_parameters,
)

from .dispatch_scenarios import(
    create_required_dispatch_scenarios,
    save_required_dispatch_scenarios,
)

from.market_data_integration import(
    prepare_experiment_data,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RESULTS_DIRECTORY = (
    PROJECT_ROOT / "results"
)

REAL_INPUT_PATH = (
    RESULTS_DIRECTORY / "week4_real_market_inputs_15min.csv"
)

def main() -> None:
    """Generate and save the five real-signal schedules."""

    load_dotenv(
        PROJECT_ROOT / "src" / ".env"
    )

    api_key = os.getenv(
        "ELECTRICITY_MAPS_API_KEY"
    )

    if api_key is None:
        raise ValueError(
            "Electricity Maps API key not available."
        )

    config = ExperimentConfig(
        start_date="2026-08-25",
        number_of_days=2,
        carbon_weight=0.20,
        degradation_cost_per_kWh=0.03,
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

    experiment_data = prepare_experiment_data(
        config=config,
        api_key=api_key,
    )

    experiment_data.real_market_data.to_csv(
        REAL_INPUT_PATH,
        index=False
    )

    scenarios = create_required_dispatch_scenarios(
        experiment_data.real_market_data,
        battery_parameters,
        carbon_weight=config.carbon_weight,
        degradation_cost_per_kWh=(
            config.degradation_cost_per_kWh
        ),
        time_step_minutes=int(config.timestep_hours * 60),
        expected_timezone=config.timezone,
    )

    saved_paths = save_required_dispatch_scenarios(
        scenarios,
        RESULTS_DIRECTORY,
    )

    print(
        "Saved common real-market input: "
        f"{REAL_INPUT_PATH}"
    )

    for scenario_name, output_path in (
        saved_paths.items()
    ):
        print(
            f"Saved {scenario_name}: "
            f"{output_path}"
        )

if __name__ == "__main__":
    main()