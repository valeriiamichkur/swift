from datetime import date, datetime, timedelta, timezone
from math import isfinite
from numbers import Real
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")

DAY_TYPES = ("weekday", "weekend")

# Risk threshold, in bikes: a station is "low" when it is expected to have at most
# this many bikes, and "high" when it is expected to have at most this many free docks.
# 0 means strictly empty / strictly full. The UI slider uses the default and range below.
DEFAULT_THRESHOLD = 2
THRESHOLD_RANGE = (0, 10)


def day_type(moment: date) -> str:
    """'weekday' for Monday-Friday, 'weekend' for Saturday and Sunday."""
    return "weekday" if moment.weekday() < 5 else "weekend"


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

        key = (day_type(local_time), local_time.hour)

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
    threshold=0,
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

    # More bikes than capacity is real (e.g. valet service at busy
    # stations), so only a negative count is rejected.
    if bikes < 0:
        raise ValueError(
            "The current number of bikes cannot be negative"
        )

    threshold = _number(threshold, "threshold")

    if threshold < 0:
        raise ValueError("Threshold cannot be negative")

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

    if expected <= threshold:
        status = "low"
    elif expected >= capacity - threshold:
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

'''тестові дані'''

if __name__ == "__main__":
    ny = ZoneInfo("America/New_York")

    current_time = datetime(
        2026, 11, 16, 14, 0, tzinfo=ny
    )
    target_time = datetime(
        2026, 11, 16, 15, 0, tzinfo=ny
    )

    test_cases = [
        ("Empty station", 3, 20, -5, -2, "low"),
        ("Exactly empty", 4, 20, -4, 0, "low"),
        ("Balanced station", 10, 20, 2, 12, "medium"),
        ("Exactly full", 18, 20, 2, 20, "high"),
        ("Overflow station", 18, 20, 6, 24, "high"),
        ("No change", 10, 20, 0, 10, "medium"),
    ]

    for (
        name,
        bikes,
        capacity,
        flow,
        expected,
        status,
    ) in test_cases:
        result = predict_station_availability(
            num_bikes_available=bikes,
            capacity=capacity,
            current_time=current_time,
            target_time=target_time,
            hourly_flows={
                ("weekday", 14): flow,
            },
        )

        assert result["expected"] == expected, name
        assert result["status"] == status, name
        assert result["net_flow"] == flow, name
        assert result["bounded_expected"] == max(
            0, min(capacity, expected)
        ), name

        print(
            f"{name}: "
            f"expected={result['expected']}, "
            f"status={result['status']} — PASS"
        )

    partial_hour = predict_station_availability(
        num_bikes_available=10,
        capacity=20,
        current_time=datetime(
            2026, 11, 16, 14, 30, tzinfo=ny
        ),
        target_time=datetime(
            2026, 11, 16, 15, 30, tzinfo=ny
        ),
        hourly_flows={
            ("weekday", 14): -4,
            ("weekday", 15): 2,
        },
    )

    assert partial_hour["net_flow"] == -1
    assert partial_hour["expected"] == 9
    assert partial_hour["status"] == "medium"

    print("Partial hours: PASS")

    overnight = predict_station_availability(
        num_bikes_available=10,
        capacity=20,
        current_time=datetime(
            2026, 11, 20, 23, 30, tzinfo=ny
        ),
        target_time=datetime(
            2026, 11, 21, 0, 30, tzinfo=ny
        ),
        hourly_flows={
            ("weekday", 23): -4,
            ("weekend", 0): 2,
        },
    )

    assert overnight["net_flow"] == -1
    assert overnight["expected"] == 9
    assert overnight["status"] == "medium"

    print("Weekday to weekend: PASS")

    threshold_cases = [
        ("Near empty", 3, 20, -1, 2, "low"),
        ("Near full", 17, 20, 1, 2, "high"),
        ("Comfortable", 10, 20, 0, 2, "medium"),
    ]

    for name, bikes, capacity, flow, threshold, status in threshold_cases:
        result = predict_station_availability(
            num_bikes_available=bikes,
            capacity=capacity,
            current_time=current_time,
            target_time=target_time,
            hourly_flows={("weekday", 14): flow},
            threshold=threshold,
        )
        assert result["status"] == status, name

    print("Threshold: PASS")

    overfull = predict_station_availability(
        num_bikes_available=25,
        capacity=20,
        current_time=current_time,
        target_time=target_time,
        hourly_flows={("weekday", 14): 0},
    )

    assert overfull["status"] == "high"
    assert overfull["bounded_expected"] == 20

    print("More bikes than capacity: PASS")
    print("\nAll forecast tests passed!")