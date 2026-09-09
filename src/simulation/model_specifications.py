from dataclasses import dataclass
from ..dispatch.battery import Battery

@dataclass
class MicrogridSpecification:
    """Store the physical equipment selected for a simulation."""

    battery: Battery
    pv_capacity_kw: float
    load_kw: float

    def __post_init__(self) -> None:
        """Validate the specification immediately after creation."""

        if not isinstance(self.battery, Battery):
            raise TypeError(
                "battery must be a Battery object"
            )

        if self.pv_capacity_kw <= 0:
            raise ValueError(
                "PV capacity must be positive."
            )

        if self.load_kw < 0:
            raise ValueError(
                "Load power must not be negative."
            )