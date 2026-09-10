"""Carbon-weight entry modes and scenario naming.

The frontend offers three ways to enter carbon weights -- a single value, an
explicit list, or an inclusive generated range -- and all three collapse to
one validated, deterministic tuple of floats here.

Ranges are generated with :class:`decimal.Decimal`. Accumulating ``0.1`` in
binary floating point drifts (``0.1 * 3 != 0.30000000000000004`` is famously
not the value anyone typed), which would make an inclusive range miss its
stated endpoint and would produce scenario names that do not round-trip.
"""

from decimal import Decimal, InvalidOperation

import math

# An inclusive range must land on its stated end. Decimal generation is exact
# for the decimal literals a user types, so this tolerance only absorbs the
# float conversion at the very end.
RANGE_ENDPOINT_TOLERANCE = 1e-9

# Each weight is a full optimization run, so a fat-fingered interval turns
# into hours of compute. Refuse rather than accept silently.
MAX_GENERATED_SCENARIOS = 100

SINGLE = "single"
LIST = "list"
RANGE = "range"

CARBON_WEIGHT_MODES = (SINGLE, LIST, RANGE)


class CarbonWeightError(ValueError):
    pass


def _to_decimal(value, label: str) -> Decimal:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise CarbonWeightError(
            f"{label} must be a number; received {value!r}."
        ) from error

    if not decimal_value.is_finite():
        raise CarbonWeightError(
            f"{label} must be finite; received {value!r}."
        )

    return decimal_value


def _validate_weight(value, label: str) -> float:
    try:
        weight = float(value)
    except (TypeError, ValueError) as error:
        raise CarbonWeightError(
            f"{label} must be a number; received {value!r}."
        ) from error

    if not math.isfinite(weight):
        raise CarbonWeightError(
            f"{label} must be finite; received {value!r}."
        )

    if weight < 0:
        raise CarbonWeightError(
            f"{label} must not be negative; received {weight}."
        )

    return weight


def _deduplicate(weights: list[float]) -> tuple[float, ...]:
    """Drop repeats while preserving first-seen order."""

    seen: list[float] = []

    for weight in weights:
        if weight not in seen:
            seen.append(weight)

    return tuple(seen)


def expand_carbon_weights(
    mode: str,
    *,
    value: float | None = None,
    values: list[float] | None = None,
    start: float | None = None,
    end: float | None = None,
    interval: float | None = None,
    max_scenarios: int = MAX_GENERATED_SCENARIOS,
) -> tuple[float, ...]:
    """Turn any entry mode into a validated tuple of carbon weights."""

    key = str(mode).strip().lower()

    if key == SINGLE:
        weights = [_validate_weight(value, "Carbon weight")]

    elif key == LIST:
        if not values:
            raise CarbonWeightError(
                "Carbon weight list must contain at least one value."
            )

        weights = [
            _validate_weight(item, f"Carbon weight at position {position}")
            for position, item in enumerate(values)
        ]

    elif key == RANGE:
        weights = _generate_range(
            start=start,
            end=end,
            interval=interval,
            max_scenarios=max_scenarios,
        )

    else:
        raise CarbonWeightError(
            f"Unknown carbon weight mode {mode!r}. "
            f"Supported modes: {list(CARBON_WEIGHT_MODES)}."
        )

    unique_weights = _deduplicate(weights)

    if not unique_weights:
        raise CarbonWeightError("Carbon weight expansion produced no values.")

    if len(unique_weights) > max_scenarios:
        raise CarbonWeightError(
            f"Carbon weight expansion produced {len(unique_weights)} "
            f"scenarios, above the limit of {max_scenarios}."
        )

    return unique_weights


def _generate_range(
    *,
    start,
    end,
    interval,
    max_scenarios: int,
) -> list[float]:
    """Generate an inclusive range that lands exactly on ``end``."""

    for label, value in (
        ("Range start", start),
        ("Range end", end),
        ("Range interval", interval),
    ):
        if value is None:
            raise CarbonWeightError(f"{label} is required for a range.")

    decimal_start = _to_decimal(start, "Range start")
    decimal_end = _to_decimal(end, "Range end")
    decimal_interval = _to_decimal(interval, "Range interval")

    if decimal_start < 0:
        raise CarbonWeightError(
            f"Range start must not be negative; received {start}."
        )

    if decimal_interval <= 0:
        raise CarbonWeightError(
            f"Range interval must be positive; received {interval}."
        )

    if decimal_end < decimal_start:
        raise CarbonWeightError(
            f"Range end ({end}) must be at least the start ({start})."
        )

    span = decimal_end - decimal_start

    if span % decimal_interval != 0:
        raise CarbonWeightError(
            f"An inclusive range from {start} to {end} does not land exactly "
            f"on {end} with interval {interval}. The span {span} is not a "
            f"whole multiple of the interval."
        )

    step_count = int(span / decimal_interval)

    if step_count + 1 > max_scenarios:
        raise CarbonWeightError(
            f"Range from {start} to {end} with interval {interval} would "
            f"generate {step_count + 1} scenarios, above the limit of "
            f"{max_scenarios}. Widen the interval or shorten the range."
        )

    weights = [
        float(decimal_start + decimal_interval * step)
        for step in range(step_count + 1)
    ]

    # Decimal arithmetic is exact for the literals a user types; this guards
    # the final float conversion.
    if abs(weights[-1] - float(decimal_end)) > RANGE_ENDPOINT_TOLERANCE:
        raise CarbonWeightError(
            f"Generated range ended at {weights[-1]} instead of {end}."
        )

    return weights


def format_carbon_weight(weight: float, decimals: int = 2) -> str:
    """Format a weight for a scenario name: 0.2 becomes '0.20'."""

    return f"{_validate_weight(weight, 'Carbon weight'):.{decimals}f}"


def build_scenario_name(
    base_name: str,
    weight: float,
    decimals: int = 2,
) -> str:
    """Deterministic scenario name, for example ``combined_optimal_0.20``."""

    if not str(base_name).strip():
        raise CarbonWeightError("Scenario base name must not be empty.")

    return f"{base_name}_{format_carbon_weight(weight, decimals)}"


def build_scenario_names(
    base_name: str,
    weights: tuple[float, ...],
    decimals: int = 2,
) -> dict[str, float]:
    """Map deterministic scenario names to their carbon weights.

    Two distinct weights that format identically would silently collide, so
    that is an error rather than a lost scenario.
    """

    names: dict[str, float] = {}

    for weight in weights:
        name = build_scenario_name(base_name, weight, decimals)

        if name in names:
            raise CarbonWeightError(
                f"Carbon weights {names[name]} and {weight} both format to "
                f"scenario name {name!r}. Increase `decimals` to tell them "
                f"apart."
            )

        names[name] = weight

    return names
