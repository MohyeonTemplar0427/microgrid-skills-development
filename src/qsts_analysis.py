"""Analyze OpenDSs Quasai Static Timeseries simulation results. """
import pandas as pd

def create_no_battery_replay_schedule(
        dispatch_data:pd.DataFrame,
)-> pd.DataFrame:
    """Create a counterfactual schedule with no battery operation"""
    required_column = {
        "load_kw",
        "pv_kw",
        "battery_net_injection_kw",
        "grid_net_import_kw",
    }

    missing_columns = (
        required_column - set(dispatch_data.columns)
    )

    if missing_columns:
        raise ValueError(
            "No-battery replay is missing required columns: " 
            f"{sorted(missing_columns)}"
        )

    no_battery_data = dispatch_data.copy()

    no_battery_data[
        "battery_net_injection_kw"
    ] = 0.0

    if "battery_charge_kw" in no_battery_data.columns:
        no_battery_data["battery_charge_kw"] = 0.0

    if "battery_discharge_kw" in no_battery_data.columns:
        no_battery_data["battery_discharge_kw"] = 0.0

    net_site_load_kw = (
        no_battery_data["load_kw"] - no_battery_data["pv_kw"]
    )

    no_battery_data["grid_net_import_kw"] = (
        net_site_load_kw
    )

    if "grid_import_kw" in no_battery_data.columns:
        no_battery_data["grid_import_kw"] = (
            net_site_load_kw.clip(lower=0.0)
        )

    if "grid_export_kw" in no_battery_data.columns:
        no_battery_data["grid_export_kw"] = (
            (-net_site_load_kw).clip(lower=0.0)
        )    
    return no_battery_data



def create_qsts_scenario_comparison(
        scenario_results: dict[str, pd.DataFrame],
        *,
        timestep_hours: float = 0.25,
)-> pd.DataFrame:
    """Summarize electrical results for multiple QSTS scenarios."""

    if not scenario_results:
        raise ValueError(
            "At least one QSTS scenario is required."
        )

    if timestep_hours <= 0:
        raise ValueError(
            "Timestep hours must be positive."
        )

    required_columns = {
        "converged",
        "minimum_voltage_pu",
        "maximum_voltage_pu",
        "maximum_current_a",
        "scheduled_grid_import_kw",
        "feeder_real_loss_kw",
        "feasible",
        "voltage_violation",
        "line_overload",
        "transformer_overload",
        "reverse_power_flow",
        "line_loading_percent",
        "transformer_loading_percent",
        "transformer_real_loss_kw",
        "pcc_grid_import_kw",
        "pcc_grid_export_kw",
    }

    comparison_records = []

    for scenario_name, results in scenario_results.items():
        missing_columns = (
            required_columns - set(results.columns)
        )

        if missing_columns:
            raise ValueError(
                f"{scenario_name} QSTS results are missing"
                f"required columns: {sorted(missing_columns)}"
            )

        if results.empty:
            raise ValueError(
                f"{scenario_name} QSTS results must not be empty."
            )

        comparison_records.append(
            {
                "scenario": scenario_name,
                "interval_count": len(results),
                "converged_intervals": int(
                    results["converged"].sum()
                ),
                "minimum_voltage_pu": (
                    results["minimum_voltage_pu"].min()
                ),
                "maximum_current_a": (
                    results["maximum_current_a"].max()
                ),
                "maximum_voltage_pu": (
                    results["maximum_voltage_pu"].max()
                ),
                "peak_grid_import_kw": (
                    results["scheduled_grid_import_kw"].max()
                ),
                "minimum_grid_power_kw": (
                    results["scheduled_grid_import_kw"].min()
                ),
                "feeder_loss_energy_kWh": (
                    results["feeder_real_loss_kw"].sum()
                    * timestep_hours
                ),
                "feasible_intervals": int(
                    results["feasible"].sum()
                ),
                "voltage_violation_intervals": int(
                    results["voltage_violation"].sum()
                ),
                "line_overload_intervals": int(
                    results["line_overload"].sum()
                ),
                "transformer_overload_intervals": int(
                    results["transformer_overload"].sum()
                ),
                "reverse_power_flow_intervals": int(
                    results["reverse_power_flow"].sum()
                ),
                "maximum_line_loading_percent": (
                    results["line_loading_percent"].max()
                ),
                "maximum_transformer_loading_percent": (
                    results["transformer_loading_percent"].max()
                ),
                "grid_import_energy_kWh": (
                    results["pcc_grid_import_kw"].sum()
                    * timestep_hours
                ),
                "grid_export_energy_kWh": (
                    results["pcc_grid_export_kw"].sum()
                    * timestep_hours
                ),
                "transformer_loss_energy_kWh": (
                    results["transformer_real_loss_kw"].sum()
                    * timestep_hours
                ),
            }
        )

    return pd.DataFrame(comparison_records)