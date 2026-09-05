import pandas as pd
from . import single_day_analysis as sda


def apply_daily_variation(
        daily_data: pd.DataFrame,
        load_factor: float,
        pv_factor: float,
        price_factor: float,
        carbon_factor: float,
) -> pd.DataFrame:
    
    varied_data = daily_data.copy()

    varied_data["load_kw"] = (
        varied_data["load_kw"]
        * load_factor
    )

    varied_data["pv_kw"] = (
        varied_data["pv_kw"]
        * pv_factor
    )

    varied_data["price_per_kWh"] = (
        varied_data["price_per_kWh"]
        * price_factor
    )

    varied_data["gCO2/kWh"] = (
        varied_data["gCO2/kWh"]
        * carbon_factor
    )

    varied_data["net_load_kw"] = (
        varied_data["load_kw"]
        - varied_data["pv_kw"]
    )

    return varied_data

def create_multi_day_dataframe(
    start_date: str,
    number_of_days: int,
) ->pd.DataFrame:

    if number_of_days <= 0:
        raise ValueError(
            "number_of_days must be greater than 0."
        )

    daily_dataframes = []

    start_timestamp = pd.Timestamp(start_date)
    load_factors = [
        1.00,
        1.05,
        0.98,
        1.03,
        1.08,
        0.92,
        0.90,
    ]

    weather_conditions = [
        "sunny",
        "partly_cloudy",
        "cloudy",
        "sunny",
        "partly_cloudy",
        "cloudy",
        "sunny",
    ]

    grid_conditions = [
        "normal",
        "high_price",
        "clean_grid",
        "normal",
        "high_price",
        "dirty_grid",
        "clean_grid",
    ]


    grid_factors = {
    "normal": {
        "price": 1.00,
        "carbon": 1.00,
    },
    "high_price": {
        "price": 1.15,
        "carbon": 1.00,
    },
    "clean_grid": {
        "price": 0.95,
        "carbon": 0.75,
    },
    "dirty_grid": {
        "price": 1.05,
        "carbon": 1.20,
    },
}
    

    pv_factor_by_weather = {
        "sunny": 1.00,
        "partly_cloudy": 0.75,
        "cloudy": 0.45,
    }
    
    for day_offset in range(number_of_days):

        current_date = (
            start_timestamp
            + pd.Timedelta(days=day_offset)
        )

        factor_index = (
            day_offset
            % len(load_factors)
        )

        grid_condition = grid_conditions[
            factor_index
        ]

        price_factor = grid_factors[
            grid_condition
        ]["price"]

        carbon_factor = grid_factors[
            grid_condition
        ]["carbon"]

        is_weekend = (
            current_date.dayofweek >= 5
        )

        if is_weekend:
            calendar_load_factor = 0.85
        else:
            calendar_load_factor = 1.00

        weather = weather_conditions[
            factor_index
        ]

        pv_factor = pv_factor_by_weather[
            weather
        ]

        final_load_factor = (
            load_factors[factor_index]
            * calendar_load_factor
        )

        daily_data = sda.create_sample_dataframe(
            date=current_date.strftime("%Y-%m-%d")
        )

        daily_data = apply_daily_variation(
            daily_data,
            load_factor=final_load_factor,
            pv_factor=pv_factor,
            price_factor=price_factor,
            carbon_factor=carbon_factor,
        )

        daily_dataframes.append(
            daily_data
        )

    multi_day_data = pd.concat(
        daily_dataframes,
        ignore_index=True,
    )

    return multi_day_data

#optimize each day separately and concatenate the seven optimized daily results
def run_daily_reset_optimization(
        horizon_data: pd.DataFrame,
)-> pd.DataFrame:

    optimized_days = []

    for _, daily_data in horizon_data.groupby(
        horizon_data["timestamp"].dt.date
    ):
        optimized_day = sda.run_combined_optimization(
            daily_data.copy(),
            sda.battery_parameters,
            carbon_weight=0.20,
            degradation_cost_per_kWh=0.03,
        )

        optimized_days.append(
            optimized_day
        )

    daily_reset_data = pd.concat(
        optimized_days,
        ignore_index=True,
    )

    return daily_reset_data

def calculate_daily_metrics(
        data: pd.DataFrame,
) -> pd.DataFrame:

    daily_results = []

    for date, daily_data in data.groupby(
        data["timestamp"].dt.date
    ):
        dispatch_metrics = sda.calculate_dispatch_metrics(
            daily_data
        )

        battery_metrics = sda.calculate_battery_usage_metrics(
            daily_data,
            sda.battery_parameters
        )

        daily_results.append(
            {
                "date": date,
                "grid_import_kWh": dispatch_metrics["grid_import_kWh"],
                "cost": dispatch_metrics["cost"],
                "emissions_kgCO2": dispatch_metrics["emissions_kgCO2"],
                "throughput_kWh": battery_metrics["throughput_kWh"],
                "equivalent_full_cycles": battery_metrics[
                    "equivalent_full_cycles"
                ],
            }
        )
    daily_metrics = pd.DataFrame(
        daily_results,
    )

    return daily_metrics


def create_horizon_comparison(
    horizon_data: pd.DataFrame,
    daily_reset_data: pd.DataFrame,
) -> pd.DataFrame:

    horizon_dispatch = sda.calculate_dispatch_metrics(
        horizon_data
    )

    horizon_battery = sda.calculate_battery_usage_metrics(
        horizon_data,
        sda.battery_parameters,
    )

    daily_dispatch = sda.calculate_dispatch_metrics(
        daily_reset_data
    )

    daily_battery = sda.calculate_battery_usage_metrics(
        daily_reset_data,
        sda.battery_parameters,
    )

    comparison = pd.DataFrame(
        [
            {
                "strategy": "Full horizon",
                "grid_import_kWh": horizon_dispatch[
                    "grid_import_kWh"
                ],
                "cost": horizon_dispatch["cost"],
                "emissions_kgCO2": horizon_dispatch[
                    "emissions_kgCO2"
                ],
                "throughput_kWh": horizon_battery[
                    "throughput_kWh"
                ],
                "equivalent_full_cycles": horizon_battery[
                    "equivalent_full_cycles"
                ],
            },
            {
                "strategy": "Daily reset",
                "grid_import_kWh": daily_dispatch[
                    "grid_import_kWh"
                ],
                "cost": daily_dispatch["cost"],
                "emissions_kgCO2": daily_dispatch[
                    "emissions_kgCO2"
                ],
                "throughput_kWh": daily_battery[
                    "throughput_kWh"
                ],
                "equivalent_full_cycles": daily_battery[
                    "equivalent_full_cycles"
                ],
            },
        ]
    )

    return comparison


def validate_multi_day_data(
    data: pd.DataFrame,
    number_of_days: int,
    timestep_minutes: int = 15,
) -> None:

    intervals_per_day = (
        24 * 60 // timestep_minutes
    )

    expected_rows = (
        number_of_days
        * intervals_per_day
    )

    if len(data) != expected_rows:
        raise ValueError(
            "Unexpected number of rows."
        )

    if not data["timestamp"].is_unique:
        raise ValueError(
            "Duplicate timestamps found."
        )

    if not data["timestamp"].is_monotonic_increasing:
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
        time_differences == expected_timestep
    ).all():
        raise ValueError(
            "Timestamps are not continuous"
        )

    if data.isna().any().any():
        raise ValueError(
            "Missing values found."
        )

def validate_multi_day_results(
    horizon_data: pd.DataFrame,
    horizon_optimized_data: pd.DataFrame,
    daily_reset_data: pd.DataFrame,
) -> None:

    expected_rows = len(
        horizon_data
    )

    if len(horizon_optimized_data) != expected_rows:
        raise ValueError(
            "Full-horizon result has an unexpected number of rows."
        )

    if len(daily_reset_data) != expected_rows:
        raise ValueError(
            "Daily-reset result has an unexpected number of rows."
        )

    sda.validate_dispatch(
        daily_reset_data,
        sda.battery_parameters,
    )



#Main()-------------------------------------------------------------------------------
if __name__ == "__main__":

    number_of_days = 14

    #---------------- INPUT DATA -------------------------------

    horizon_data = create_multi_day_dataframe(
        start_date="2026-08-01",
        number_of_days=number_of_days,
    )

    validate_multi_day_data(
        horizon_data,
        number_of_days,
    )


    # ---------------- FULL-HORIZON OPTIMIZATION ----------------

    horizon_optimized_data = sda.run_combined_optimization(
        horizon_data.copy(),
        sda.battery_parameters,
        carbon_weight=0.20,
        degradation_cost_per_kWh=0.03,
    )

    sda.validate_dispatch(
        horizon_optimized_data,
        sda.battery_parameters,
    )

    horizon_dispatch_metrics = (
        sda.calculate_dispatch_metrics(
            horizon_optimized_data
        )
    )

    horizon_battery_usage = (
        sda.calculate_battery_usage_metrics(
            horizon_optimized_data,
            sda.battery_parameters,
        )
    )


    # ---------------- DAILY-RESET OPTIMIZATION ----------------

    daily_reset_data = run_daily_reset_optimization(
        horizon_data
    )

    validate_multi_day_results(
        horizon_data,
        horizon_optimized_data,
        daily_reset_data,
    )

    daily_reset_metrics = (
        sda.calculate_dispatch_metrics(
            daily_reset_data
        )
    )

    daily_reset_battery_usage = (
        sda.calculate_battery_usage_metrics(
            daily_reset_data,
            sda.battery_parameters,
        )
    )


    # ---------------- DAILY METRICS ----------------

    horizon_daily_metrics = calculate_daily_metrics(
        horizon_optimized_data
    )

    daily_reset_daily_metrics = calculate_daily_metrics(
        daily_reset_data
    )

    # ---------------- HORIZON COMPARISON ----------------

    horizon_comparison = create_horizon_comparison(
        horizon_optimized_data,
        daily_reset_data,
    )

    horizon_row = horizon_comparison[
        horizon_comparison["strategy"]
        == "Full horizon"
    ].iloc[0]

    daily_row = horizon_comparison[
        horizon_comparison["strategy"]
        == "Daily reset"
    ].iloc[0]


    # ---------------- PERCENT DIFFERENCES ----------------

    grid_import_diff_percent = (
        (
            horizon_row["grid_import_kWh"]
            - daily_row["grid_import_kWh"]
        )
        / daily_row["grid_import_kWh"]
        * 100
    )

    throughput_diff_percent = (
        (
            horizon_row["throughput_kWh"]
            - daily_row["throughput_kWh"]
        )
        / daily_row["throughput_kWh"]
        * 100
    )

    efc_diff_percent = (
        (
            horizon_row["equivalent_full_cycles"]
            - daily_row["equivalent_full_cycles"]
        )
        / daily_row["equivalent_full_cycles"]
        * 100
    )

    cost_diff_percent = (
        (
            horizon_row["cost"]
            - daily_row["cost"]
        )
        / daily_row["cost"]
        * 100
    )

    emissions_diff_percent = (
        (
            horizon_row["emissions_kgCO2"]
            - daily_row["emissions_kgCO2"]
        )
        / daily_row["emissions_kgCO2"]
        * 100
    )


    # ---------------- RESULTS ----------------

    print(
        "\nFull-horizon metrics:",
        horizon_dispatch_metrics,
    )

    print(
        "\nFull-horizon battery usage:",
        horizon_battery_usage,
    )

    print(
        "\nDaily-reset metrics:",
        daily_reset_metrics,
    )

    print(
        "\nDaily-reset battery usage:",
        daily_reset_battery_usage,
    )

    print(
        "\nFull horizon vs daily reset:"
    )

    print(
        f"Grid import difference: "
        f"{grid_import_diff_percent:.2f}%"
    )

    print(
        f"Battery throughput difference: "
        f"{throughput_diff_percent:.2f}%"
    )

    print(
        f"EFC difference: "
        f"{efc_diff_percent:.2f}%"
    )

    print(
        f"Cost difference: "
        f"{cost_diff_percent:.2f}%"
    )

    print(
        f"Emissions difference: "
        f"{emissions_diff_percent:.2f}%"
    )



    