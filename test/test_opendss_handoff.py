import pandas as pd
import pytest

from src.opendss.opendss_handoff import create_opendss_handoff


def test_create_opendss_handoff_uses_documented_signs():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=2,
        freq="15min",
        tz="America/Los_Angeles",
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [5.0, 2.0],
            "pv_kw": [0.0, 4.0],
            "battery_charge_kw": [2.0, 0.0],
            "battery_discharge_kw": [0.0, 1.5],
            "grid_import_kw": [7.0, 0.0],
            "grid_export_kw": [0.0, 3.5],
            "battery_soc_kWh": [10.5, 10.1],
        }
    )

    result = create_opendss_handoff(
        dispatch_data
    )

    assert result.loc[
        0,
        "battery_net_injection_kw",
    ] == pytest.approx(-2.0)

    assert result.loc[
        1,
        "battery_net_injection_kw",
    ] == pytest.approx(1.5)

    assert result.loc[
        0,
        "grid_net_import_kw",
    ] == pytest.approx(7.0)

    assert result.loc[
        1,
        "grid_net_import_kw",
    ] == pytest.approx(-3.5)


def test_create_opendss_handoff_rejects_missing_interval():
    timestamps = pd.DatetimeIndex(
        [
            pd.Timestamp(
                "2026-08-25 00:00",
                tz="America/Los_Angeles",
            ),
            pd.Timestamp(
                "2026-08-25 00:15",
                tz="America/Los_Angeles",
            ),
            pd.Timestamp(
                "2026-08-25 00:45",
                tz="America/Los_Angeles",
            ),
        ]
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [5.0, 5.0, 5.0],
            "pv_kw": [1.0, 1.0, 1.0],
            "battery_charge_kw": [0.0, 0.0, 0.0],
            "battery_discharge_kw": [0.0, 0.0, 0.0],
            "grid_import_kw": [4.0, 4.0, 4.0],
            "grid_export_kw": [0.0, 0.0, 0.0],
            "battery_soc_kWh": [10.0, 10.0, 10.0],
        }
    )

    with pytest.raises(
        ValueError,
        match="not continuous 15-minute intervals",
    ):
        create_opendss_handoff(
            dispatch_data
        )



def test_create_opendss_handoff_rejects_infinite_value():
    timestamps = pd.date_range(
        start="2026-08-25 00:00",
        periods=2,
        freq="15min",
        tz="America/Los_Angeles",
    )

    dispatch_data = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": [
                5.0,
                float("inf"),
            ],
            "pv_kw": [1.0, 1.0],
            "battery_charge_kw": [0.0, 0.0],
            "battery_discharge_kw": [0.0, 0.0],
            "grid_import_kw": [4.0, 4.0],
            "grid_export_kw": [0.0, 0.0],
            "battery_soc_kWh": [10.0, 10.0],
        }
    )

    with pytest.raises(
        ValueError,
        match="contains non-finite values",
    ):
        create_opendss_handoff(
            dispatch_data
        )
