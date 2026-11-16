from datetime import datetime, timedelta, timezone
from math import isfinite
from numbers import Real
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field}: a number is required")

    value = float(value)

    if not isfinite(value):
        raise ValueError(
            f"{field}: a finite number is required"
        )

    return value


def _calculate_flow(
    current_time,
    target_time,
    hourly_flows,
):
    for value in (current_time, target_time):
        if (
            not isinstance(value, datetime)
            or value.utcoffset() is None
        ):
            raise ValueError(
                "Time must be a timezone-aware datetime"
            )

    cursor = current_time.astimezone(timezone.utc)
    end = target_time.astimezone(timezone.utc)

    if end < cursor:
        raise ValueError(
            "Target time cannot be earlier "
            "than the current measurement time"
        )

    total_flow = 0.0

    while cursor < end:
        local_time = cursor.astimezone(NEW_YORK)

        if local_time.weekday() < 5:
            day_type = "weekday"
        else:
            day_type = "weekend"

        key = (day_type, local_time.hour)

        hourly_flow = _number(
            hourly_flows[key],
            "hourly_flow",
        )

        next_hour = (
            cursor.replace(
                minute=0,
                second=0,
                microsecond=0,
            )
            + timedelta(hours=1)
        )

        interval_end = min(next_hour, end)

        hours = (
            interval_end - cursor
        ).total_seconds() / 3600

        total_flow += hourly_flow * hours
        cursor = interval_end

    return total_flow


def predict_station_availability(
    num_bikes_available,
    capacity,
    current_time,
    target_time,
    hourly_flows,
):
    bikes = _number(
        num_bikes_available,
        "num_bikes_available",
    )
    capacity = _number(capacity, "capacity")

    if capacity <= 0:
        raise ValueError(
            "Capacity must be greater than zero"
        )

    if not 0 <= bikes <= capacity:
        raise ValueError(
            "The current number of bikes must be "
            "between zero and capacity"
        )

    net_flow = _calculate_flow(
        current_time,
        target_time,
        hourly_flows,
    )

    expected = bikes + net_flow

    if not isfinite(expected):
        raise ValueError(
            "The forecast exceeds the supported "
            "numeric range"
        )

    if expected <= 0:
        status = "low"
    elif expected >= capacity:
        status = "high"
    else:
        status = "medium"

    return {
        "expected": expected,
        "bounded_expected": max(
            0.0,
            min(capacity, expected),
        ),
        "net_flow": net_flow,
        "fill_ratio": expected / capacity,
        "status": status,
        "target_time": target_time.isoformat(),
    }