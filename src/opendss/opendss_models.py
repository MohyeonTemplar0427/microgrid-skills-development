"""Data models used by the OpenDSS analysis."""

from dataclasses import dataclass
from enum import Enum


class LoadingStatus(Enum):
    """Possible feeder-loading conditions."""

    NORMAL = "normal"
    EMERGENCY = "emergency"
    ABOVE_EMERGENCY = "above_emergency"


@dataclass(frozen=True)
class FeederMetrics:
    """Electrical measurements calculated for the feeder."""

    phase_currents_a: tuple[float, ...]
    input_real_power_kw: float
    input_reactive_power_kvar: float
    apparent_power_kva: float
    power_factor: float
    real_loss_kw: float
    reactive_absorption_kvar: float


@dataclass(frozen=True)
class TransformerMetrics:
    """Electrical measurements and loading for a transformer."""

    input_real_power_kw: float
    input_reactive_power_kvar: float
    apparent_power_kva: float
    rated_power_kva: float
    loading_percent: float
    real_loss_kw: float
    reactive_absorption_kvar: float


@dataclass(frozen=True)
class PCCMetrics:
    """Power exchange measured at the point of common coupling."""

    grid_net_import_kw: float
    grid_import_kw: float
    grid_export_kw: float
    reactive_power_kvar: float
    apparent_power_kva: float
    reverse_power_flow: bool


@dataclass(frozen=True)
class LineLoadingAssessment:
    """Feeder loading compared with its current ratings."""

    maximum_current_a: float
    normal_rating_a: float
    emergency_rating_a: float
    normal_loading_percent: float
    emergency_loading_percent: float
    status: LoadingStatus


@dataclass(frozen=True)
class VoltageAssessment:
    """Bus-voltage compliance assessment."""

    minimum_voltage_pu: float
    maximum_voltage_pu: float
    within_limits: bool
