"""Tests for ExperimentConfig's demand-charge fields."""

import pytest

from src.dispatch.config import ExperimentConfig


def test_demand_charge_fields_default_to_disabled():
    config = ExperimentConfig(
        start_date="2026-08-25",
        number_of_days=2,
    )

    assert config.demand_charge_rate_per_kw == 0.0
    assert config.previous_peak_kw is None


def test_demand_charge_fields_accept_explicit_values():
    config = ExperimentConfig(
        start_date="2026-08-25",
        number_of_days=2,
        demand_charge_rate_per_kw=20.50,
        previous_peak_kw=275.0,
    )

    assert config.demand_charge_rate_per_kw == pytest.approx(20.50)
    assert config.previous_peak_kw == pytest.approx(275.0)


def test_rejects_negative_demand_charge_rate():
    with pytest.raises(ValueError):
        ExperimentConfig(
            start_date="2026-08-25",
            number_of_days=2,
            demand_charge_rate_per_kw=-1.0,
        )


def test_rejects_negative_previous_peak():
    with pytest.raises(ValueError):
        ExperimentConfig(
            start_date="2026-08-25",
            number_of_days=2,
            previous_peak_kw=-1.0,
        )
