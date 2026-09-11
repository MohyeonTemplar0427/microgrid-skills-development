"""Normalized, timezone-aware interval tables for the optimizer."""

from .interval_table import (
    IntervalIndex,
    NormalizedIntervalTable,
    align_to_index,
    build_interval_index,
    build_interval_index_from_days,
    build_normalized_table,
    from_legacy_columns,
    normalize_any_frame,
    to_legacy_columns,
)
from .schema import (
    DEFAULT_TIMESTEP_MINUTES,
    MissingDataPolicy,
    PowerUnit,
    convert_to_kw,
)
from .validation import IntervalTableError, validate_interval_table

__all__ = [
    "DEFAULT_TIMESTEP_MINUTES",
    "IntervalIndex",
    "IntervalTableError",
    "MissingDataPolicy",
    "NormalizedIntervalTable",
    "PowerUnit",
    "align_to_index",
    "build_interval_index",
    "build_interval_index_from_days",
    "build_normalized_table",
    "convert_to_kw",
    "from_legacy_columns",
    "normalize_any_frame",
    "to_legacy_columns",
    "validate_interval_table",
]
