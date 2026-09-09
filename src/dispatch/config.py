from .battery import Battery
from dataclasses import dataclass

battery = Battery(
    capacity_kWh = 20.0,
    energy_kWh = 10.0,
    max_charge_kw=5.0,
    max_discharge_kw=5.0
)

@dataclass
## Configuration for the experiment, attributes are set for simpliciy, but for later use,
## it will inclue more parameters for the experiment.
class ExperimentConfig:
    start_date: str
    number_of_days: int

    carbon_weight: float = 0.20
    degradation_cost_per_kWh: float = 0.03
    timestep_hours: float = 0.25

    caiso_node: str = "TH_NP15_GEN-APND"
    electricity_maps_zone: str = "US-CAL-CISO"

    timezone: str = "America/Los_Angeles"
    sleep_seconds: float = 1.0

    def __post_init__(self) -> None:
        
        if self.number_of_days <= 0:
            raise ValueError("Number of days must be greater than 0.")

        if self.timestep_hours <= 0:
            raise ValueError("timestep_hours must be greater than 0.")

        if self.carbon_weight < 0:
            raise ValueError("Carbon weight must be greater than 0.")

        if self.degradation_cost_per_kWh < 0:
            raise ValueError("Degradation cost per kWh must be greater than 0.")

        if self.sleep_seconds < 0:
            raise ValueError("Sleep seconds must be greater than 0.")
            
def to_optimizer_parameters(
        self,
) -> dict[str, float]:

    return {
        "capacity_kWh": self.capacity_kWh,
        "initial_soc_kWh": self.energy_kWh,
        "min_soc_kWh": self.minimum_energy_kWh,
        "max_soc_kWh": self.maximum_energy_kWh,
        "max_charge_kw": self.max_charge_kw,
        "max_discharge_kw": self.max_discharge_kw,
        "charge_efficiency": self.charge_efficiency,
        "discharge_efficiency": self.discharge_efficiency
    }

