"""Tests for Electricity Maps range retrieval."""

import pandas as pd

import src.signal_pipeline.electricity_maps_data as electricity_maps


def test_multi_day_carbon_data_uses_short_continuous_chunks(monkeypatch):
    calls = []

    def fake_get_range(_api_key, _zone, start, end):
        calls.append((start, end))
        timestamps = pd.date_range(
            start=start,
            end=end,
            freq="15min",
            inclusive="left",
        )

        return {
            "temporalGranularity": "15_minutes",
            "data": [
                {
                    "datetime": timestamp.isoformat(),
                    "carbonIntensity": 300,
                }
                for timestamp in timestamps
            ],
        }

    monkeypatch.setattr(
        electricity_maps,
        "get_carbon_intensity_range",
        fake_get_range,
    )

    result = electricity_maps.get_multi_day_carbon_data(
        "test-key",
        "US-CAL-CISO",
        "2026-08-25",
        7,
        timezone="America/Los_Angeles",
    )

    assert len(calls) == 4
    assert calls[0] == (
        "2026-08-25T07:00:00Z",
        "2026-08-27T07:00:00Z",
    )
    assert calls[-1] == (
        "2026-08-31T07:00:00Z",
        "2026-09-01T07:00:00Z",
    )
    assert len(result) == 7 * 96
    assert result["timestamp"].is_unique
