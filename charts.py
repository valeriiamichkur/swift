from math import isfinite
from numbers import Real
import pandas as pd


TABLE_COLUMNS = {
    "station_id": "Station ID",
    "name": "Station",
    "num_bikes_available": "Current Bikes",
    "capacity": "Capacity",
    "net_flow": "Net Flow over Period",
    "expected": "Expected Bikes",
}


def _fill_ratio(station):
    expected = station["expected"]
    capacity = station["capacity"]

    for value in (expected, capacity):
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not isfinite(value)
        ):
            raise ValueError(
                "Expected bikes and capacity must be "
                "finite numbers"
            )

    if capacity <= 0:
        raise ValueError(
            "Capacity must be greater than zero"
        )

    return expected / capacity


def build_risk_tables(stations, limit=10):
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit < 0
    ):
        raise ValueError(
            "limit must be a non-negative integer"
        )

    low = []
    high = []

    for station in stations:
        status = station["status"]

        if status not in ("low", "medium", "high"):
            raise ValueError(
                f"Unknown status: {status}"
            )

        ratio = _fill_ratio(station)

        if status == "low":
            low.append((ratio, dict(station)))
        elif status == "high":
            high.append((ratio, dict(station)))

    low.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("station_id", "")),
        )
    )

    high.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("station_id", "")),
        )
    )

    low_rows = [
        station
        for _, station in low[:limit]
    ]

    high_rows = [
        station
        for _, station in high[:limit]
    ]

    low_table = pd.DataFrame(
        low_rows,
        columns=list(TABLE_COLUMNS),
    ).rename(columns=TABLE_COLUMNS)

    high_table = pd.DataFrame(
        high_rows,
        columns=list(TABLE_COLUMNS),
    ).rename(columns=TABLE_COLUMNS)

    return low_table, high_table


def map_points(stations):
    """One row per station with lat, lon and status; styling is in station_map.py."""
    frame = pd.DataFrame(
        list(stations),
        columns=["lat", "lon", "status"],
    )

    return frame.dropna(subset=["lat", "lon"])
