from dataclasses import dataclass,field

@dataclass
class Battery:
    capacity_kWh: float = 50

    SOC_min: float = 0.2
    minimum_energy_kWh: float = field(init = False)

    SOC_max: float = 0.8
    maximum_energy_kWh: float = field(init = False)

    SOC_range: float = field(init = False)
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    max_charge_kw: float = 20
    max_discharge_kw: float = 20
    energy_kWh: float = 10

    def __post_init__(self) -> None:

        if self.capacity_kWh <= 0:
            raise ValueError("Capacity must be positive.")

        self.minimum_energy_kWh = self.capacity_kWh * self.SOC_min
        self.maximum_energy_kWh = self.capacity_kWh * self.SOC_max
        self.SOC_range = self.SOC_max - self.SOC_min

        if self.minimum_energy_kWh <= 0:
            raise ValueError("Minimumenergy must be positive.")
        
        if self.maximum_energy_kWh <= 0:
            raise ValueError("Maximumenergy must be positive.")
        
        if not self.minimum_energy_kWh <= self.energy_kWh <= self.maximum_energy_kWh:
            raise ValueError("Energy must be between minimum and maximum energy.")

        if self.max_charge_kw <= 0:
            raise ValueError("Maximum charge power must be positive.")
        
        if self.max_discharge_kw <= 0:
            raise ValueError("Maximum discharge power must be positive.")
        
        if not 0 < self.charge_efficiency <= 1:
            raise ValueError("Charge efficiency must be between 0 and 1.")
        
        if not 0 < self.discharge_efficiency <= 1:
            raise ValueError("Discharge efficiency must be between 0 and 1.")


    def SOC_percentage(self) -> float: 
        return (self.energy_kWh / self.capacity_kWh) * 100


    def update_energy(
        self,
        charge_kw: float,
        discharge_kw: float,
        dt_hours: float = 0.25,
    ) -> float:
        self._validate_power_command(
            charge_kw = charge_kw,
            discharge_kw = discharge_kw,
            dt_hours = dt_hours,
        )

        next_energy_kWh = self.energy_kWh + (charge_kw * self.charge_efficiency - discharge_kw / self.discharge_efficiency) * dt_hours
        
        if next_energy_kWh > self.maximum_energy_kWh:
            raise ValueError("Energy must be less than maximum energy.")
        
        if next_energy_kWh < self.minimum_energy_kWh:
            raise ValueError("Energy must be greater than minimum energy.")
        
        self.energy_kWh = next_energy_kWh
        
        return self.energy_kWh

    def _validate_power_command(
        self,
        charge_kw:float,
        discharge_kw: float,
        dt_hours: float,
    ) -> None:
        if charge_kw < 0:
            raise ValueError("Charge power must be non-negative.")

        if discharge_kw < 0:
            raise ValueError("Discharge power must be non-negative.")

        if charge_kw > self.max_charge_kw:
            raise ValueError("Charge power must be less than maximum charge power.")

        if discharge_kw > self.max_discharge_kw:
            raise ValueError("Discharge power must be less than maximum discharge power.")

        if discharge_kw > 0 and charge_kw > 0:
            raise ValueError("Cannot charge and discharge simultaneously.")

        if dt_hours <= 0:
            raise ValueError("Timestep must be positive")

def calculate_grid_power(
    load_kw:float,
    pv_kw: float,
    charge_kw: float,
    discharge_kw: float,
    ) -> float:
        if pv_kw < 0:
            raise ValueError("PV power must be non-negative.")
        if load_kw < 0:
            raise ValueError("Load power must be non-negative.")
        grid_import = load_kw +charge_kw - discharge_kw - pv_kw
        return grid_import 

def simulate_timestep(
    battery: Battery,
    load_kw: float,
    pv_kw: float,
    charge_kw: float,
    discharge_kw: float,
    dt_hours: float = 0.25,
) -> dict[str, float]:
    if load_kw < 0 or pv_kw < 0:
        raise ValueError("Load power and PV power must be non-negative.")
    
    battery.update_energy(
        charge_kw = charge_kw,
        discharge_kw = discharge_kw,
        dt_hours = dt_hours,
    )

    grid_import = calculate_grid_power(
        load_kw=load_kw,
        pv_kw=pv_kw,
        charge_kw=charge_kw,
        discharge_kw=discharge_kw,
    )
    return {
        "energy_kWh": battery.energy_kWh,
        "SOC_percentage": battery.SOC_percentage(),
        "grid_import": grid_import,
    }

###This is the main function to run the battery simulation
if __name__ == "__main__":
    battery = Battery()

    print("Battery created successfully")
    print(f"Capacity: {battery.capacity_kWh:.2f} kWh")
    print(f"Minimum energy: {battery.minimum_energy_kWh:.2f} kWh")
    print(f"Maximum energy: {battery.maximum_energy_kWh:.2f} kWh")
    print(f"Current energy: {battery.energy_kWh:.2f} kWh")
    print(f"Current SOC: {battery.SOC_percentage():.2f}%")

    print("\nCharging for 15 minutes...")

    battery.update_energy(
        charge_kw=5.0,
        discharge_kw=0.0,
        dt_hours=0.25,
    )

    print(f"Energy after charging: {battery.energy_kWh:.2f} kWh")
    print(f"SOC after charging: {battery.SOC_percentage():.2f}%")

    print("\nDischarging for 15 minutes...")

    battery.update_energy(
        charge_kw=0.0,
        discharge_kw=4.0,
        dt_hours=0.25,
    )

    print(f"Energy after discharging: {battery.energy_kWh:.2f} kWh")
    print(f"SOC after discharging: {battery.SOC_percentage():.2f}%")
    grid_import = calculate_grid_power(
        load_kw=30.0,
        pv_kw=20.0,
        charge_kw=100.0,
        discharge_kw=0.0,
    )
    print(f"Grid power: {grid_import:.2f} kW")

