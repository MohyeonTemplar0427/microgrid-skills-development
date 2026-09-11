import pandas as pd
import math
import matplotlib.pyplot as plt
import cvxpy as cp
from typing import cast

from .dispatch_metrics import (
    calculate_battery_usage_metrics,
    calculate_dispatch_metrics,
)

def create_time_index(
        date: str,
        timezone: str = "America/Los_Angeles"
) -> pd.DatetimeIndex:

    """Creating one day of 15-minute timestamps"""

    timestamps = pd.date_range(
        start = date,
        periods = 96,
        freq = "15min",
        tz = timezone,
    )

    return timestamps


def create_pv_profile(
        timestamps: pd.DatetimeIndex,
        maximum_pv_kw: float = 30.0,
) -> list[float]:
    """Create a simplified solar-PV profile"""

    pv_values = []

    for timestamp in timestamps:
        hour = timestamp.hour + timestamp.minute / 60

        if 6 <= hour < 18:
            solar_fraction = math.sin(math.pi * (hour - 6) / 12)
            pv_kw = maximum_pv_kw * solar_fraction
        else:
            pv_kw = 0.0

        pv_values.append(max(pv_kw, 0.0))

    return pv_values


#Create a synthetic average-carbon-intensity profile 
def create_carbon_profile(
        timestamps: pd.DatetimeIndex,
) -> list[float]:
    carbon_intensity_values = []

    for timestamp in timestamps:
        hour = timestamp.hour + timestamp.minute / 60

        if 0 <= hour < 6:
            carbon_intensity = 320.0
        elif 6 <= hour < 12:
            carbon_intensity = 250.0
        elif 12 <= hour < 17:
            carbon_intensity = 120.0
        elif 17 <= hour < 22:
            carbon_intensity = 380.0
        else:
            carbon_intensity = 300.0

        carbon_intensity_values.append(carbon_intensity)

    return carbon_intensity_values 
    


def create_price_profile(
        timestamps: pd.DatetimeIndex,
) -> list[float]:
    price_values = []

    for timestamp in timestamps:
        hour = timestamp.hour + timestamp.minute / 60

        if 0 <= hour < 6:
            price_per_kwh = 0.12
        elif 6 <= hour < 16:
            price_per_kwh = 0.20
        elif 16 <= hour < 21:
            price_per_kwh = 0.38
        else:
            price_per_kwh = 0.16

        price_values.append(price_per_kwh)

    return price_values



def create_load_profile(
        timestamps: pd.DatetimeIndex,
) -> list[float]:

    #Create a simple daily electrical-load profile

    load_values = []

    for timestamp in timestamps:
        hour = timestamp.hour + timestamp.minute / 60
        if 0 <= hour < 6:
            load_kw = 15.0
        elif 6 <= hour < 12:
            load_kw = 25.0
        elif 12 <= hour < 17:
            load_kw = 35.0
        else:
            load_kw = 20.0

        load_values.append(load_kw)

    return load_values

"""Create and validate a one-day microgrid time-series table."""
def create_sample_dataframe(
    date: str,
    timezone: str = "America/Los_Angeles",
) -> pd.DataFrame:
    #Create the initial one-day time-series table.

    timestamps = create_time_index(
        date=date,
        timezone=timezone,
    )

    load_values = create_load_profile(timestamps)
    pv_values = create_pv_profile(timestamps)
    price_values = create_price_profile(timestamps)
    carbon_intensity_values = create_carbon_profile(timestamps)


    data = pd.DataFrame({
        "timestamp": timestamps,
        "load_kw": load_values,
        "pv_kw": pv_values,
        "price_per_kWh": price_values,
        "gCO2/kWh": carbon_intensity_values,
    })

    validate_sample_data(data)

    data["net_load_kw"] = (
        data["load_kw"] - data["pv_kw"]
    )
    
    return data

def validate_sample_data(data: pd.DataFrame) -> None:

    required_columns = {
        "timestamp",
        "load_kw",
        "pv_kw",
        "price_per_kWh",
        "gCO2/kWh",
        }
    
    difference = required_columns - set(data.columns)

    if difference:
        raise ValueError(
            f"Missing DataFrame columns: {difference}"
            )

    ## Check if we have 96 time intervals to fully cover a day
    if len(data) != 96:
        raise ValueError(f"Expected 96 intervals, but received {len(data)}.")
    
    ## Check if there is any missing entry in the DataFrame
    if data.isna().any().any():
        raise ValueError("There is one or more missing values in the DataFrame.")

    ## Check if there is no overlap in time interval
    if not data["timestamp"].is_unique:
        raise ValueError("Not every timestamp is unique.")

    ## Check if timestamp is increasing chronologically 
    if not data["timestamp"].is_monotonic_increasing:
        raise ValueError("Timestamps must increase chronologically.")

    time_differences = data["timestamp"].diff()
    time_differences = time_differences.dropna()

    if not (time_differences == pd.Timedelta(minutes=15)).all():
        raise ValueError(
            "Time intervals must be 15 minutes"
        )
    # Check if each timestamp has timezone
    if data["timestamp"].dt.tz is None:
        raise ValueError(
            "Timestamps must include timezone information"
                         )

    # Check if four numerical inputs don't have negative values.
    numeric_columns = [
        "load_kw",
        "pv_kw",
        "price_per_kWh",
        "gCO2/kWh",
    ]

    if (data[numeric_columns] < 0).any().any():
        raise ValueError(
            "Numerical input values must be nonnegative."
        )

battery_parameters = {
    "capacity_kWh": 20.0,
    "initial_soc_kWh": 10.0,
    "min_soc_kWh": 2.0,
    "max_soc_kWh": 18.0,
    "max_charge_kw": 5.0,
    "max_discharge_kw": 5.0,
    "charge_efficiency": 0.95,
    "discharge_efficiency": 0.95
}

# System parameters:
# battery capacity, SOC limits, power limits, efficiencies

# State variable:
# battery_soc_kWh

# Decision variables:
# battery_charge_kw
# battery_discharge_kw

# Resulting grid variables:
# grid_import_kw
# grid_export_kw

def run_carbon_optimization(
        data: pd.DataFrame,
        battery_parameters: dict[str, float],
        *,
        timestep_hours: float = 0.25,
)->pd.DataFrame:

    number_of_steps = len(data)

    if timestep_hours <= 0:
        raise ValueError("Timestep hours must be positive.")

    initial_soc_kWh = battery_parameters["initial_soc_kWh"]
    min_soc_kWh = battery_parameters["min_soc_kWh"]
    max_soc_kWh = battery_parameters["max_soc_kWh"]

    max_charge_kw = battery_parameters["max_charge_kw"]
    max_discharge_kw = battery_parameters["max_discharge_kw"]

    charge_efficiency = battery_parameters["charge_efficiency"]
    discharge_efficiency = battery_parameters["discharge_efficiency"]

    constraints = []

    battery_charge_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    battery_discharge_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    grid_import_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    grid_export_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    #need one more soc states as soc is state variable
    battery_soc_kWh = cp.Variable(
        number_of_steps + 1
    )
    constraints.append(
        battery_soc_kWh[0] == initial_soc_kWh
    )

    constraints.append(
        battery_soc_kWh[-1] == initial_soc_kWh
    )

    constraints += [
        battery_charge_kw <= max_charge_kw,
        battery_discharge_kw <= max_discharge_kw,
        battery_soc_kWh >= min_soc_kWh, 
        battery_soc_kWh <= max_soc_kWh,
    ]

    for t in range(number_of_steps):
        constraints.append(
            battery_soc_kWh[t + 1]
            ==
            battery_soc_kWh[t]
            + battery_charge_kw[t]
            * timestep_hours
            * charge_efficiency
            - battery_discharge_kw[t]
            * timestep_hours
            / discharge_efficiency
        )

        constraints.append(
            data["pv_kw"].iloc[t]
            + grid_import_kw[t]
            + battery_discharge_kw[t]
            ==
            data["load_kw"].iloc[t]
            + battery_charge_kw[t]
            + grid_export_kw[t]       
        )

    grid_import_emissions = cp.sum(
        cp.multiply(
            grid_import_kw,
            data["gCO2/kWh"].to_numpy(),
        )
    ) * timestep_hours

    objective = cp.Minimize(
        grid_import_emissions
    )

    problem = cp.Problem(
        objective,
        constraints,
    )

    problem.solve()

    if problem.status not in ["optimal", "optimal_inaccurate"]:
            raise ValueError(
                f"Optimization failed with stats; {problem.status}"
            )
    objective_value = problem.value

    if objective_value is None:
        raise ValueError(
            "Carbon optimization did not return an objective value."
        )
    
    objective_value = float(cast(float, objective_value))

    if problem.status not in ["optimal", "optimal_inaccurate"]:
        raise ValueError(
            f"Optimization failed with stats; {problem.status}"
        )

    soc_values = battery_soc_kWh.value

    if soc_values is None:
        raise ValueError(
            "Optimizer did not return battery SOC values."
        )
    
    data["battery_soc_kWh"] = soc_values[1:]
    data["battery_charge_kw"] = battery_charge_kw.value
    data["battery_discharge_kw"] = battery_discharge_kw.value
    data["grid_import_kw"] = grid_import_kw.value
    data["grid_export_kw"] = grid_export_kw.value

    data["power_balance_error_kw"] = (
        data["pv_kw"]
        + data["battery_discharge_kw"]
        + data["grid_import_kw"]
        - data["load_kw"]
        - data["battery_charge_kw"]
        - data["grid_export_kw"]
    )

    return data



def run_cost_optimization(
        data: pd.DataFrame,
        battery_parameters: dict[str, float],
        *,
        degradation_cost_per_kWh: float = 0.0,
        timestep_hours: float = 0.25,
) -> pd.DataFrame:

    number_of_steps = len(data)

    if timestep_hours <= 0:
        raise ValueError("Timestep hours must be positive.")

    if degradation_cost_per_kWh < 0:
        raise ValueError(
            "Degradation cost must not be negative."
        )

    initial_soc_kWh = battery_parameters["initial_soc_kWh"]
    min_soc_kWh = battery_parameters["min_soc_kWh"]
    max_soc_kWh = battery_parameters["max_soc_kWh"]

    max_charge_kw = battery_parameters["max_charge_kw"]
    max_discharge_kw = battery_parameters["max_discharge_kw"]

    charge_efficiency = battery_parameters["charge_efficiency"]
    discharge_efficiency = battery_parameters["discharge_efficiency"]

    constraints = []

    battery_charge_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    battery_discharge_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    grid_import_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    grid_export_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    #need one more soc states as soc is state variable
    battery_soc_kWh = cp.Variable(
        number_of_steps + 1
    )
    constraints.append(
        battery_soc_kWh[0] == initial_soc_kWh
    )

    constraints.append(
        battery_soc_kWh[-1] == initial_soc_kWh
    )

    constraints += [
        battery_charge_kw <= max_charge_kw,
        battery_discharge_kw <= max_discharge_kw,
        battery_soc_kWh >= min_soc_kWh, 
        battery_soc_kWh <= max_soc_kWh,
    ]

    for t in range(number_of_steps):
        constraints.append(
            battery_soc_kWh[t + 1]
            ==
            battery_soc_kWh[t]
            + battery_charge_kw[t]
            * timestep_hours
            * charge_efficiency
            - battery_discharge_kw[t]
            * timestep_hours
            / discharge_efficiency
        )

        constraints.append(
            data["pv_kw"].iloc[t]
            + grid_import_kw[t]
            + battery_discharge_kw[t]
            ==
            data["load_kw"].iloc[t]
            + battery_charge_kw[t]
            + grid_export_kw[t]       
        )

    grid_import_cost = cp.sum(
        cp.multiply(
            grid_import_kw,
            data["price_per_kWh"].to_numpy(),
        )
    ) * timestep_hours

    battery_throughput_kWh = (
        cp.sum(battery_charge_kw)
        + cp.sum(battery_discharge_kw)
    ) * timestep_hours

    battery_degradation_cost = (
        degradation_cost_per_kWh
        * battery_throughput_kWh
    )

    objective = cp.Minimize(
        grid_import_cost
        + battery_degradation_cost
    )

    problem = cp.Problem(
        objective,
        constraints,
    )

    problem.solve()

    if problem.status not in ["optimal", "optimal_inaccurate"]:
        raise ValueError(
            f"Optimization failed with stats; {problem.status}"
        )

    soc_values = battery_soc_kWh.value

    if soc_values is None:
        raise ValueError(
            "Optimizer did not return battery SOC values."
        )
    
    data["battery_soc_kWh"] = soc_values[1:]
    data["battery_charge_kw"] = battery_charge_kw.value
    data["battery_discharge_kw"] = battery_discharge_kw.value
    data["grid_import_kw"] = grid_import_kw.value
    data["grid_export_kw"] = grid_export_kw.value

    data["power_balance_error_kw"] = (
        data["pv_kw"]
        + data["battery_discharge_kw"]
        + data["grid_import_kw"]
        - data["load_kw"]
        - data["battery_charge_kw"]
        - data["grid_export_kw"]
    )

    return data




# This function returns data table updated with updated grid parameter histories
def run_rule_based_dispatch(
        data: pd.DataFrame,
        battery_parameters: dict[str, float],
        strategy: str = "price",
        *,
        timestep_hours: float = 0.25,
) -> pd.DataFrame:

    if timestep_hours <= 0:
        raise ValueError("Timestep hours must be positive.")

    discharge_price_threshold = 0.30
    discharge_carbon_threshold = 350.0

    ##System Parameters
    battery_capacity_kWh = battery_parameters["capacity_kWh"]
    battery_soc_kWh = battery_parameters["initial_soc_kWh"]

    target_final_soc_kWh = battery_parameters["initial_soc_kWh"]
    recovery_start_hour = 21

    min_soc_kWh = battery_parameters["min_soc_kWh"]
    max_soc_kWh = battery_parameters["max_soc_kWh"]

    max_charge_kw = battery_parameters["max_charge_kw"]
    max_discharge_kw = battery_parameters["max_discharge_kw"]

    charge_efficiency = battery_parameters["charge_efficiency"]
    discharge_efficiency = battery_parameters["discharge_efficiency"]

    ##Data log
    battery_soc_history = []
    battery_charge_history = []
    battery_discharge_history = []
    grid_import_history = []
    grid_export_history = []

    for index, row in data.iterrows():
        net_load_kw = row["net_load_kw"]
        price_per_kWh = row["price_per_kWh"]
        carbon_intensity = row["gCO2/kWh"]

        battery_charge_kw = 0.0
        battery_discharge_kw = 0.0
        grid_import_kw = 0.0
        grid_export_kw = 0.0

        if strategy == "price":
            discharge_allowed = (
                price_per_kWh >= discharge_price_threshold
            )
        elif strategy == "carbon":
            discharge_allowed = (
                carbon_intensity >= discharge_carbon_threshold
            )
        else:
            raise ValueError(
                f"Unknown dispatch strategy: {strategy}"
            )

        if net_load_kw > 0 and discharge_allowed:
            deficit_kw = net_load_kw

            available_energy_kWh = (
                battery_soc_kWh - min_soc_kWh
            )

            soc_limited_discharge_kw = (
                available_energy_kWh * discharge_efficiency / timestep_hours
            )

            battery_discharge_kw = min(
                deficit_kw,
                max_discharge_kw,
                soc_limited_discharge_kw,
            )

            battery_soc_kWh -= (
                battery_discharge_kw
                * timestep_hours
                / discharge_efficiency
            )

            grid_import_kw = (
                deficit_kw - battery_discharge_kw
            )

        elif net_load_kw > 0:
            grid_import_kw = net_load_kw

        elif net_load_kw < 0:
            excess_pv_kw = abs(net_load_kw)

            available_storage_kWh = (
                max_soc_kWh - battery_soc_kWh
            )
            soc_limited_charge_kw = (
                available_storage_kWh
                / charge_efficiency
                / timestep_hours
            )

            battery_charge_kw = min(
                excess_pv_kw,
                max_charge_kw,
                soc_limited_charge_kw
            )

            battery_soc_kWh += (
                battery_charge_kw
                * timestep_hours
                * charge_efficiency
            )

            grid_export_kw = (
                excess_pv_kw - battery_charge_kw
            )

        hour = row["timestamp"].hour

        if (
            strategy == "price"
            and hour >= recovery_start_hour
            and battery_soc_kWh < target_final_soc_kWh
        ):
            needed_storage_kWh = (
                target_final_soc_kWh - battery_soc_kWh
            )

            soc_limited_charge_kw = (
                needed_storage_kWh
                / charge_efficiency
                / timestep_hours
            )

            battery_charge_kw = min(
                max_charge_kw,
                soc_limited_charge_kw,
            )

            battery_soc_kWh += (
                battery_charge_kw
                * timestep_hours
                * charge_efficiency
            )

            grid_import_kw += battery_charge_kw

        battery_soc_history.append(battery_soc_kWh)
        battery_charge_history.append(battery_charge_kw)
        battery_discharge_history.append(battery_discharge_kw)
        grid_import_history.append(grid_import_kw)
        grid_export_history.append(grid_export_kw)

    data["battery_soc_kWh"] = battery_soc_history
    data["battery_charge_kw"] = battery_charge_history
    data["battery_discharge_kw"] = battery_discharge_history
    data["grid_import_kw"] = grid_import_history
    data["grid_export_kw"] = grid_export_history
    data["power_balance_error_kw"] = (
        data["pv_kw"]
        + data["battery_discharge_kw"]
        + data["grid_import_kw"]
        - data["load_kw"]
        - data["battery_charge_kw"]
        - data["grid_export_kw"]
    )
    data["grid_import_energy_kWh"] = (
        data["grid_import_kw"] 
        * timestep_hours
        )

    data["grid_import_cost"] = (
        data["grid_import_energy_kWh"]
        * data["price_per_kWh"]
    )

    return data

#Combined optimization considring the degradation cost per kWh and carbon weight of electriciy
def run_combined_optimization(
        data: pd.DataFrame,
        battery_parameters: dict[str, float],
        carbon_weight: float,
        degradation_cost_per_kWh: float,
        timestep_hours: float = 0.25,
)->pd.DataFrame:

    number_of_steps = len(data)

    if timestep_hours <= 0:
        raise ValueError("Timestep hours must be positive.")

    initial_soc_kWh = battery_parameters["initial_soc_kWh"]
    min_soc_kWh = battery_parameters["min_soc_kWh"]
    max_soc_kWh = battery_parameters["max_soc_kWh"]

    max_charge_kw = battery_parameters["max_charge_kw"]
    max_discharge_kw = battery_parameters["max_discharge_kw"]

    charge_efficiency = battery_parameters["charge_efficiency"]
    discharge_efficiency = battery_parameters["discharge_efficiency"]

    constraints = []

    battery_charge_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    battery_discharge_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    grid_import_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    grid_export_kw = cp.Variable(
        number_of_steps,
        nonneg=True,
    )

    #need one more soc states as soc is state variable
    battery_soc_kWh = cp.Variable(
        number_of_steps + 1
    )


    constraints.append(
        battery_soc_kWh[0] == initial_soc_kWh
    )

    constraints.append(
        battery_soc_kWh[-1] == initial_soc_kWh
    )

    constraints += [
        battery_charge_kw <= max_charge_kw,
        battery_discharge_kw <= max_discharge_kw,
        battery_soc_kWh >= min_soc_kWh, 
        battery_soc_kWh <= max_soc_kWh,
    ]

    for t in range(number_of_steps):
        constraints.append(
            battery_soc_kWh[t + 1]
            ==
            battery_soc_kWh[t]
            + battery_charge_kw[t]
            * timestep_hours
            * charge_efficiency
            - battery_discharge_kw[t]
            * timestep_hours
            / discharge_efficiency
        )

        constraints.append(
            data["pv_kw"].iloc[t]
            + grid_import_kw[t]
            + battery_discharge_kw[t]
            ==
            data["load_kw"].iloc[t]
            + battery_charge_kw[t]
            + grid_export_kw[t]       
        )

    grid_import_cost = cp.sum(
        cp.multiply(
            grid_import_kw,
            data["price_per_kWh"].to_numpy(),
        )
    ) * timestep_hours

    grid_import_emission_kgCO2 = (
        cp.sum(
            cp.multiply(
                grid_import_kw,
                data["gCO2/kWh"].to_numpy(),
            )
        )
        * timestep_hours 
        / 1000
    ) 

    battery_throughput_kWh = (
        cp.sum(battery_charge_kw)
        + cp.sum(battery_discharge_kw)
    ) * timestep_hours

    battery_degradation_cost = (
        degradation_cost_per_kWh
        * battery_throughput_kWh
    )

    objective = cp.Minimize(
        grid_import_cost
        + carbon_weight
        * grid_import_emission_kgCO2
        + battery_degradation_cost
    )

    problem = cp.Problem(
        objective,
        constraints,
    )

    problem.solve()

    if problem.status not in ["optimal", "optimal_inaccurate"]:
        raise ValueError(
            f"Optimization failed with stats; {problem.status}"
        )

    soc_values = battery_soc_kWh.value

    if soc_values is None:
        raise ValueError(
            "Optimizer did not return battery SOC values."
        )
    
    data["battery_soc_kWh"] = soc_values[1:]
    data["battery_charge_kw"] = battery_charge_kw.value
    data["battery_discharge_kw"] = battery_discharge_kw.value
    data["grid_import_kw"] = grid_import_kw.value
    data["grid_export_kw"] = grid_export_kw.value

    data["power_balance_error_kw"] = (
        data["pv_kw"]
        + data["battery_discharge_kw"]
        + data["grid_import_kw"]
        - data["load_kw"]
        - data["battery_charge_kw"]
        - data["grid_export_kw"]
    )

    return data


#Plotting Results----------------------------------------------------------------------- 
def plot_dispatch_results(
        data: pd.DataFrame,
)-> None:
    figure, axes = plt.subplots(
        3,
        1,
        figsize = (10, 8),
        sharex=True,
    )

    axes[0].plot(
        data["timestamp"],
        data["battery_soc_kWh"],
    )

    axes[0].set_title("Battery State of Charge")
    axes[0].set_ylabel("Energy (kWh)")

    axes[1].plot(
        data["timestamp"],
        data["battery_discharge_kw"],
        label="Discharge"
    )
    axes[1].plot(
            data["timestamp"],
            data["battery_charge_kw"],
            label="Charge"
        )    

    axes[1].set_title("Battery Power")
    axes[1].set_ylabel("Power (kW)")
    axes[1].legend()

    axes[2].plot(
        data["timestamp"],
        data["grid_import_kw"],
        label="Import",
    )
    axes[2].plot(
        data["timestamp"],
        data["grid_export_kw"],
        label="Export",
    )

    axes[2].set_title("Grid Exchange")
    axes[2].set_ylabel("Power (kW)")
    axes[2].set_xlabel("Time")
    axes[2].legend()

    figure.autofmt_xdate()
    figure.tight_layout()

    plt.show()

def plot_degradation_sensitivity(
        results: pd.DataFrame,
)-> None:

    plt.figure()

    plt.plot(
        results["degradation_cost_per_kWh"],
        results["equivalent_full_cycles"],
        marker="o",
    )

    plt.xlabel(
        "Degradation Cost ($/kWh throughput)"
    )

    plt.ylabel(
        "Equivalent Full Cycles"
    )

    plt.title(
        "Battery Cycling vs Degradation Cost"
    )

    plt.grid(True)

    plt.savefig(
        "data/degradation_sensitivity.png",
        dpi=300,
        bbox_inches="tight"
        )




#Plotting the input signals-------------------------------------------------------------
def plot_input_profiles(
        data: pd.DataFrame
    ) -> None:
    figure, axes = plt.subplots(
        4,
        1,
        figsize=(9,7.5),
        sharex = True
    )
    axes[0].plot(
        data["timestamp"],
        data["load_kw"],
    )

    axes[1].plot(
        data["timestamp"],
        data["pv_kw"],
    )

    axes[2].plot(
        data["timestamp"],
        data["price_per_kWh"],
    )
    axes[3].plot(
        data["timestamp"],
        data["gCO2/kWh"],
    )
    axes[0].set_title("Electrical Load")
    axes[0].set_ylabel("Load (kW)")

    axes[1].set_title("Solar PV Generation")
    axes[1].set_ylabel("PV (kW)")

    axes[2].set_title("Electricity Price")
    axes[2].set_ylabel("Price ($/kWh)")

    axes[3].set_title("Grid Carbon Intensity")
    axes[3].set_ylabel("gCO2/kWh")
    axes[3].set_xlabel("Time")

    figure.autofmt_xdate()
    figure.tight_layout()
    figure.savefig(
        "results/input_profiles.png",
        dpi = 300,
    )

def plot_cost_emissions_tradeoff(
    results: pd.DataFrame,
) -> None:

    plt.figure()

    plt.plot(
        results["emissions_kgCO2"],
        results["cost"],
        marker="o",
    )

    label_offsets = {
        0.00: (8, 5),
        0.02: (8, 5),
        0.05: (8, 18),
        0.10: (8, 31),
        0.20: (8, 5),
    }

    for index, row in results.iterrows():

        carbon_weight = row[
            "carbon_weight_$_per_kgCO2"
        ]

        offset = label_offsets.get(
            carbon_weight,
            (5, 5),
        )

        plt.annotate(
            f"{carbon_weight:.2f}",
            (
                row["emissions_kgCO2"],
                row["cost"],
            ),
            xytext=offset,
            textcoords="offset points",
        )

    plt.xlabel(
        "Emissions (kgCO2)"
    )

    plt.ylabel(
        "Cost ($)"
    )

    plt.title(
        "Cost–Emissions Tradeoff"
    )

    plt.grid(True)
    plt.savefig("data/cost_emissions_tradeoff.png",
                dpi = 300,
                bbox_inches="tight"
    )

def validate_dispatch(
    data: pd.DataFrame,
    battery_parameters: dict[str, float],
    tolerance: float = 1e-5
) -> None:

    min_soc_kWh = battery_parameters["min_soc_kWh"]
    max_soc_kWh = battery_parameters["max_soc_kWh"]

    max_charge_kw = battery_parameters["max_charge_kw"]
    max_discharge_kw = battery_parameters["max_discharge_kw"]

    if data["battery_soc_kWh"].min() < min_soc_kWh - tolerance:
        raise ValueError(
            "Battery SOC fell below minimum SOC."
        )

    if data["battery_soc_kWh"].max() > max_soc_kWh + tolerance:
        raise ValueError(
            "Battery SOC exceeded maximum SOC."
        )

    if data["battery_charge_kw"].max() > max_charge_kw + tolerance:
        raise ValueError(
            "Battery charging power exceeded its limit."
        )

    if data["battery_discharge_kw"].max() > max_discharge_kw + tolerance:
        raise ValueError(
            "Battery discharging power exceeded its limit."
        )

    if data["power_balance_error_kw"].abs().max() > tolerance:
        raise ValueError(
            "Power balance error exceeded tolerance."
        )



##Main-------------------------------------------------------------------------------
if __name__ == "__main__":
    timestep_hours = 0.25
    data = create_sample_dataframe(
        date="2026-08-01",
    )
    ## data
    optimized_data = run_cost_optimization(
        data.copy(),
        battery_parameters,
    )

    carbon_optimized_data = run_carbon_optimization(
        data.copy(),
        battery_parameters
    )

    carbon_weights = [
        0.00,
        0.02,
        0.05,
        0.10,
        0.20,
    ]

    
    combined_data = run_combined_optimization(
        data.copy(),
        battery_parameters,
        carbon_weight = 0.20,
        degradation_cost_per_kWh=0.03,
    )
    

    simultaneous_rows = optimized_data[
        (optimized_data["battery_charge_kw"] > 0.01)
        &
        (optimized_data["battery_discharge_kw"] > 0.01)
    ]

    battery_usage_metrics = calculate_battery_usage_metrics(
        optimized_data,
        battery_parameters,
    )

    cost_battery_usage = calculate_battery_usage_metrics(
        optimized_data,
        battery_parameters,
    )

    carbon_battery_usage = calculate_battery_usage_metrics(
        carbon_optimized_data,
        battery_parameters,
    )

    combined_battery_usage = calculate_battery_usage_metrics(
        combined_data,
        battery_parameters
    )
# ---------------- COMBINED OPTIMIZATION WITH DEGRADATION ----------------

    combined_data_with_degradation = run_combined_optimization(
        data.copy(),
        battery_parameters,
        carbon_weight=0.20,
        degradation_cost_per_kWh=0.03,
    )

    combined_degradation_metrics = calculate_dispatch_metrics(
        combined_data_with_degradation
    )

    combined_degradation_battery_usage = calculate_battery_usage_metrics(
        combined_data_with_degradation,
        battery_parameters,
    )

    degradation_results = []
    degradation_costs = [
        0.00,
        0.01,
        0.03,
        0.05,
        0.10,
    ]   

    for degradation_cost in degradation_costs:

        combined_data = run_combined_optimization(
            data.copy(),
            battery_parameters,
            carbon_weight=0.20,
            degradation_cost_per_kWh=degradation_cost,
        )

        dispatch_metrics = calculate_dispatch_metrics(
            combined_data
        )

        battery_usage_metrics = calculate_battery_usage_metrics(
            combined_data,
            battery_parameters,
        )

        degradation_results.append(
            {
                "degradation_cost_per_kWh": degradation_cost,
                "cost": dispatch_metrics["cost"],
                "emissions_kgCO2": dispatch_metrics["emissions_kgCO2"],
                "throughput_kWh": battery_usage_metrics["throughput_kWh"],
                "equivalent_full_cycles": battery_usage_metrics[
                    "equivalent_full_cycles"
                ],
            }
        )

    degradation_results_df = pd.DataFrame(
        degradation_results
    )
    validate_dispatch(
        combined_data_with_degradation,
        battery_parameters,
    )

    simultaneous_grid_exchange = combined_data_with_degradation[
        (combined_data_with_degradation["grid_import_kw"] > 0.01)
        &
        (combined_data_with_degradation["grid_export_kw"] > 0.01)     
    ]

    print(
        "\nNumber of simultaneous import/export intervals:",
        len(simultaneous_grid_exchange)
    )

    if len(simultaneous_grid_exchange) > 0:
        print(
            simultaneous_grid_exchange[
                [
                    "timestamp",
                    "grid_import_kw",
                    "grid_export_kw",
                ]
            ]
        )
    else:
        print(
            "No meaningful simultaneous grid import/export found."
        )

    initial_soc_kWh = battery_parameters["initial_soc_kWh"]

    final_soc_kWh = combined_data_with_degradation[
        "battery_soc_kWh"
    ].iloc[-1]

    terminal_soc_error_kWh = abs(
        final_soc_kWh - initial_soc_kWh
    )

    print(
        "\nInitial SOC:",
        initial_soc_kWh,
    )

    print(
        "Final SOC:",
        final_soc_kWh,
    )

    print(
        "Termianl SOC error:",
        terminal_soc_error_kWh,
    )

    plot_degradation_sensitivity(
        degradation_results_df
    )






        

    
