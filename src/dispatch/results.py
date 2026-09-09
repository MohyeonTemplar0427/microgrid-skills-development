from dataclasses import dataclass, field
import pandas as pd

@dataclass
class ExperimentResult:
    no_battery_cost: float
    no_battery_emissions: float

    synthetic_real_cost: float
    synthetic_real_emissions: float

    real_market_cost: float
    real_market_emissions: float

    cost_savings: float
    emissions_reduction: float

    real_market_degradation_cost: float
    real_market_total_operating_cost: float
    operating_cost_savings: float

    synthetic_usage: dict[str, float]
    real_market_usage: dict[str, float]

    weighted_charge_price: float
    weighted_discharge_price: float

    weighted_charge_carbon: float
    weighted_discharge_carbon: float

    daily_summary: pd.DataFrame

    scenario_metrics: dict[
        str,
        dict[str, float],
    ] = field(default_factory = dict)

    opendss_handoff: pd.DataFrame = field(
        default_factory=pd.DataFrame
    )

    