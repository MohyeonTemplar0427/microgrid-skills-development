"""Run complete time-series microgrid analyses."""

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from ..timeseries import normalize_any_frame, to_legacy_columns

from ..dispatch.config import to_optimizer_parameters
from ..dispatch.dispatch_scenarios import (
    create_required_dispatch_scenarios,
)
from ..opendss.qsts_analysis import (
    create_qsts_scenario_comparison,
)
from ..opendss.validation import (
    create_dispatch_performance_summary,
    create_validation_report,
)
from .microgrid_simulator import (
    simulate_microgrid_scenarios,
)
from .model_specifications import (
    MicrogridSpecification,
)


def _normalize_signal_timestamps(
    signal_data: pd.DataFrame,
    *,
    expected_timezone: str,
) -> pd.DataFrame:
    """Convert signal timestamps to the expected named timezone."""

    if "timestamp" not in signal_data.columns:
        raise ValueError(
            "Time-series signal data is missing timestamp."
        )

    normalized_data = signal_data.copy()

    timestamps = pd.to_datetime(
        normalized_data["timestamp"],
        errors="raise",
    )

    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(
            expected_timezone,
        )
    else:
        timestamps = timestamps.dt.tz_convert(
            expected_timezone,
        )

    normalized_data["timestamp"] = timestamps

    return normalized_data


def _normalize_boundary_timestamp(
    timestamp: str | pd.Timestamp,
    *,
    expected_timezone: str,
) -> pd.Timestamp:
    """Convert one range boundary to the expected timezone."""

    normalized_timestamp = pd.Timestamp(timestamp)

    if normalized_timestamp.tzinfo is None:
        return normalized_timestamp.tz_localize(
            expected_timezone
        )

    return normalized_timestamp.tz_convert(
        expected_timezone
    )


def select_signal_time_range(
    signal_data: pd.DataFrame,
    *,
    start_time: str | pd.Timestamp,
    end_time: str | pd.Timestamp,
    expected_timezone: str = "America/Los_Angeles",
) -> pd.DataFrame:
    """Select signals within a user-defined time range."""

    normalized_data = _normalize_signal_timestamps(
        signal_data,
        expected_timezone=expected_timezone,
    )

    normalized_start = _normalize_boundary_timestamp(
        start_time,
        expected_timezone=expected_timezone,
    )

    normalized_end = _normalize_boundary_timestamp(
        end_time,
        expected_timezone=expected_timezone,
    )

    if normalized_start >= normalized_end:
        raise ValueError(
            "Analysis start time must be before end time."
        )

    selected_intervals = normalized_data.loc[
        (
            normalized_data["timestamp"]
            >= normalized_start
        )
        & (
            normalized_data["timestamp"]
            < normalized_end
        )
    ].copy()

    if selected_intervals.empty:
        raise ValueError(
            "No signal intervals exist within the selected time range."
        )

    return selected_intervals.reset_index(
        drop=True,
    )


@dataclass
class TimeSeriesAnalysisResult:
    """Store detailed and summarized time-series results."""

    dispatch_scenarios: dict[str, pd.DataFrame]
    powerflow_scenarios: dict[str, pd.DataFrame]
    comparison: pd.DataFrame


def run_microgrid_timeseries_analysis(
    specification: MicrogridSpecification,
    signal_data: pd.DataFrame,
    *,
    timestep_minutes: int = 15,
    carbon_weight: float = 0.20,
    degradation_cost_per_kWh: float = 0.03,
    expected_timezone: str = "America/Los_Angeles",
    start_time: str | pd.Timestamp | None = None,
    end_time: str | pd.Timestamp | None = None,
    scenario_names: tuple[str, ...] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> TimeSeriesAnalysisResult:
    """Run dispatch, power flow, and performance analysis."""

    if timestep_minutes <= 0:
        raise ValueError(
            "Timestep minutes must be positive."
        )

    if carbon_weight < 0:
        raise ValueError(
            "Carbon weight must not be negative."
        )

    if degradation_cost_per_kWh < 0:
        raise ValueError(
            "Degradation cost must not be negative."
        )

    if signal_data.empty:
        raise ValueError(
            "Time-series signal data must not be empty."
        )

    if start_time is None and end_time is None:
        analysis_data = _normalize_signal_timestamps(
            signal_data,
            expected_timezone=expected_timezone,
        )
    elif start_time is not None and end_time is not None:
        analysis_data = select_signal_time_range(
            signal_data,
            start_time=start_time,
            end_time=end_time,
            expected_timezone=expected_timezone,
        )
    else:
        raise ValueError(
            "Both start_time and end_time must be provided."
        )

    timestep_hours = timestep_minutes / 60.0

    analysis_data = _normalize_signal_timestamps(
        analysis_data,
        expected_timezone=expected_timezone,
    )

    canonical_analysis_data = normalize_any_frame(
        analysis_data,
        timestep_minutes=timestep_minutes,
        rated_pv_capacity_kw=specification.pv_capacity_kw,
    )
    analysis_data = to_legacy_columns(canonical_analysis_data)

    battery_parameters = to_optimizer_parameters(
        specification.battery
    )

    if progress_callback is not None:
        progress_callback("Optimizing the selected dispatch scenarios")

    dispatch_scenarios = (
        create_required_dispatch_scenarios(
            analysis_data,
            battery_parameters,
            carbon_weight=carbon_weight,
            degradation_cost_per_kWh=(
                degradation_cost_per_kWh
            ),
            time_step_minutes=timestep_minutes,
            expected_timezone=expected_timezone,
            scenario_names=scenario_names,
        )
    )

    if progress_callback is not None:
        progress_callback("Replaying dispatch through the OpenDSS network")

    powerflow_scenarios = (
        simulate_microgrid_scenarios(
            specification,
            dispatch_scenarios,
            timestep_minutes=timestep_minutes,
        )
    )

    if progress_callback is not None:
        progress_callback("Calculating cost, emissions, and electrical metrics")

    dispatch_summary = (
        create_dispatch_performance_summary(
            dispatch_scenarios,
            analysis_data,
            battery_parameters,
            degradation_cost_per_kWh=(
                degradation_cost_per_kWh
            ),
            timestep_hours=timestep_hours,
        )
    )

    powerflow_summary = (
        create_qsts_scenario_comparison(
            powerflow_scenarios,
            timestep_hours=timestep_hours,
        )
    )

    comparison = create_validation_report(
        dispatch_summary,
        powerflow_summary,
    )

    return TimeSeriesAnalysisResult(
        dispatch_scenarios=dispatch_scenarios,
        powerflow_scenarios=powerflow_scenarios,
        comparison=comparison,
    )
