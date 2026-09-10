from .battery import Battery
from dataclasses import dataclass
from ..signal_pipeline.region_config import get_region_config

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

    # The region supplies the market provider, price node, carbon zone and
    # timezone. The fields below stay None unless a caller overrides one.
    region: str = "caiso_np15"

    market_location: str | None = None
    electricity_maps_zone: str | None = None
    timezone: str | None = None

    # Deprecated alias for market_location, kept for existing CAISO callers.
    caiso_node: str | None = None

    sleep_seconds: float = 1.0

    def __post_init__(self) -> None:

        region_config = get_region_config(self.region)

        self.market_provider = region_config.market_provider
        self.carbon_provider = region_config.carbon_provider

        if self.caiso_node is not None and self.market_location is None:
            self.market_location = self.caiso_node

        if self.market_location is None:
            self.market_location = region_config.market_location

        if self.electricity_maps_zone is None:
            self.electricity_maps_zone = region_config.carbon_zone

        if self.timezone is None:
            self.timezone = region_config.timezone

        self.caiso_node = self.market_location

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

