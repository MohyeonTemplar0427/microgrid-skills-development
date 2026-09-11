"""Canonical column names and units for the normalized interval table.

Every timestamp is the **start** of its interval. Power columns are kW and
energy columns are kWh; the two are never interchangeable, and conversion
always goes through the interval duration.

The legacy schema (``load_kw``, ``pv_kw``, ``gCO2/kWh``) remains readable and
writable through :mod:`src.timeseries.adapters`, so existing result CSVs and
downstream dispatch code keep working unchanged.
"""

from enum import StrEnum

# Required columns of the normalized interval table.
TIMESTAMP = "timestamp"
NATIVE_LOAD_KW = "native_load_kw"
PV_AVAILABLE_KW = "pv_available_kw"
PRICE_PER_KWH = "price_per_kWh"
CARBON_INTENSITY_G_PER_KWH = "carbon_intensity_g_per_kWh"

REQUIRED_COLUMNS = (
    TIMESTAMP,
    NATIVE_LOAD_KW,
    PV_AVAILABLE_KW,
    PRICE_PER_KWH,
    CARBON_INTENSITY_G_PER_KWH,
)

# Optional columns; absent means the capability is disabled, not zero-valued
# by coincidence.
FLEXIBLE_LOAD_AVAILABLE_KW = "flexible_load_available_kw"
EXPORT_LIMIT_KW = "export_limit_kw"
EXPORT_PRICE_PER_KWH = "export_price_per_kWh"

OPTIONAL_COLUMNS = (
    FLEXIBLE_LOAD_AVAILABLE_KW,
    EXPORT_LIMIT_KW,
    EXPORT_PRICE_PER_KWH,
)

# Legacy names kept for backward compatibility. `pv_kw` was ambiguous: it
# meant available PV in input frames and delivered PV in dispatch output.
# The normalized schema splits those into pv_available_kw and pv_output_kw.
LEGACY_LOAD_KW = "load_kw"
LEGACY_PV_KW = "pv_kw"
LEGACY_NET_LOAD_KW = "net_load_kw"
LEGACY_CARBON = "gCO2/kWh"

LEGACY_TO_CANONICAL = {
    LEGACY_LOAD_KW: NATIVE_LOAD_KW,
    LEGACY_PV_KW: PV_AVAILABLE_KW,
    LEGACY_CARBON: CARBON_INTENSITY_G_PER_KWH,
}

CANONICAL_TO_LEGACY = {
    NATIVE_LOAD_KW: LEGACY_LOAD_KW,
    PV_AVAILABLE_KW: LEGACY_PV_KW,
    CARBON_INTENSITY_G_PER_KWH: LEGACY_CARBON,
}

# Dispatch result columns. Distinguishing available from delivered PV is the
# whole point of the surplus layer.
PV_OUTPUT_KW = "pv_output_kw"
PV_CURTAILED_KW = "pv_curtailed_kw"
FLEXIBLE_LOAD_KW = "flexible_load_kw"
TOTAL_LOAD_KW = "total_load_kw"
GRID_IMPORT_KW = "grid_import_kw"
GRID_EXPORT_KW = "grid_export_kw"
GRID_NET_IMPORT_KW = "grid_net_import_kw"
BATTERY_CHARGE_KW = "battery_charge_kw"
BATTERY_DISCHARGE_KW = "battery_discharge_kw"
BATTERY_NET_INJECTION_KW = "battery_net_injection_kw"

DEFAULT_TIMESTEP_MINUTES = 15

# Power below this is treated as zero when checking balance and simultaneity.
POWER_TOLERANCE_KW = 1e-6


class PowerUnit(StrEnum):
    """Units accepted for user-supplied power columns."""

    W = "W"
    KW = "kW"
    MW = "MW"


TO_KW = {
    PowerUnit.W: 1e-3,
    PowerUnit.KW: 1.0,
    PowerUnit.MW: 1e3,
}


def convert_to_kw(values, unit: PowerUnit | str):
    """Convert a numeric series from ``unit`` to kW."""

    try:
        power_unit = PowerUnit(unit)
    except ValueError as error:
        raise ValueError(
            f"Unsupported power unit {unit!r}. "
            f"Supported units: {[u.value for u in PowerUnit]}."
        ) from error

    return values * TO_KW[power_unit]


class MissingDataPolicy(StrEnum):
    """What to do about gaps in a user-supplied profile.

    There is no silent default: whichever policy is chosen is recorded on the
    result so a filled interval is never mistaken for a measured one.
    """

    REJECT = "reject"
    FORWARD_FILL = "forward_fill"
    INTERPOLATE = "interpolate"
    ZERO_FILL = "zero_fill"
