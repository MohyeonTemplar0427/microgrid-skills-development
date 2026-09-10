"""Define user-selected time-series analysis settings."""

from dataclasses import dataclass
from datetime import date, timedelta

SUPPORTED_STRATEGIES = frozenset(
    {
        "no_battery",
        "rule_based",
        "cost_optimal",
        "carbon_optimal",
        "combined_optimal",
    }
)

DEFAULT_STRATEGIES = (
    "no_battery",
    "rule_based",
    "cost_optimal",
    "carbon_optimal",
    "combined_optimal",
)


@dataclass
class AnalysisConfiguration:
    """Store the settings for one time-series analysis."""

    start_date: str
    number_of_days: int
    region_id: str

    timestep_minutes: int = 15
    strategies: tuple[str, ...] = DEFAULT_STRATEGIES
    carbon_weight: float = 0.20
    degradation_cost_per_kWh: float = 0.03

    def __post_init__(self) -> None:
        """Validate the analysis settings after creation."""

        try:
            date.fromisoformat(self.start_date)
        except (TypeError, ValueError):
            raise ValueError(
                "Start date must use YYYY-MM-DD format."
            )

        if self.number_of_days <= 0:
            raise ValueError(
                "Number of days must be positive."
            )

        if not self.region_id.strip():
            raise ValueError(
                "Region ID must not be empty."
            )

        if self.timestep_minutes <= 0:
            raise ValueError(
                "Timestep minutes must be positive."
            )

        if not self.strategies:
            raise ValueError(
                "At least one strategy must be selected."
            )

        if len(set(self.strategies)) != len(self.strategies):
            raise ValueError(
                "Selected strategies must not contain duplicates."
            )

        unsupported_strategies = (
            set(self.strategies)
            - SUPPORTED_STRATEGIES
        )

        if unsupported_strategies:
            raise ValueError(
                "Unsupported strategies: "
                f"{sorted(unsupported_strategies)}"
            )

        if "no_battery" not in self.strategies:
            raise ValueError(
                "The no-battery baseline must be selected."
            )

        if self.carbon_weight < 0:
            raise ValueError(
                "Carbon weight must not be negative."
            )

        if self.degradation_cost_per_kWh < 0:
            raise ValueError(
                "Degradation cost must not be negative."
            )

    @property
    def end_date(self) -> str:
        """Return the exclusive analysis end date."""

        parsed_start_date = date.fromisoformat(
            self.start_date
        )

        calculated_end_date = (
            parsed_start_date
            + timedelta(days=self.number_of_days)
        )

        return calculated_end_date.isoformat()

    @property
    def strategy_count(self) -> int:
        """Return the number of selected strategies."""

        return len(self.strategies)
