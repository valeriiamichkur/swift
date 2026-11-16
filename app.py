from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, request

DATA_PATH = Path(__file__).parent / "data" / "raw_data.csv"

app = Flask(__name__)


# ---------------------------------------------------------------- data ---

@lru_cache(maxsize=1)
def load_trips() -> pd.DataFrame:
    """Load the trip CSV once and keep it in memory."""
    df = pd.read_csv(
        DATA_PATH,
        dtype={"start_station_id": str, "end_station_id": str},
        parse_dates=["started_at", "ended_at"],
    )
    return df


@lru_cache(maxsize=1)
def load_stations() -> pd.DataFrame:
    """One row per station: id, name, coordinates (taken from trip starts and ends)."""
    df = load_trips()
    starts = df[["start_station_id", "start_station_name", "start_lat", "start_lng"]]
    starts.columns = ["station_id", "name", "lat", "lng"]
    ends = df[["end_station_id", "end_station_name", "end_lat", "end_lng"]]
    ends.columns = ["station_id", "name", "lat", "lng"]
    stations = (
        pd.concat([starts, ends])
        .dropna(subset=["station_id"])
        .groupby("station_id")
        .agg(name=("name", "first"), lat=("lat", "median"), lng=("lng", "median"))
        .reset_index()
    )
    return stations


@lru_cache(maxsize=1)
def dataset_days() -> pd.DatetimeIndex:
    """Every calendar day that appears in the trip data."""
    return pd.DatetimeIndex(load_trips()["started_at"].dt.normalize().unique())


# ------------------------------------------------------------- helpers ---

class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return jsonify({"error": err.message}), err.status


@app.errorhandler(404)
def handle_not_found(_err):
    return jsonify({"error": "unknown endpoint", "endpoints": ENDPOINTS}), 404


def parse_time(raw: str | None) -> datetime:
    """Accept ISO 8601 ('2026-09-03T08:30', '2026-09-03 08:30'); default to now."""
    if not raw:
        return datetime.now()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        raise ApiError(f"invalid time '{raw}', expected ISO format like 2026-09-03T08:30")


def require_station(station_id: str | None) -> pd.Series:
    if not station_id:
        raise ApiError("missing required parameter 'station_id'")
    stations = load_stations()
    match = stations[stations["station_id"] == station_id]
    if match.empty:
        raise ApiError(f"station '{station_id}' not found", status=404)
    return match.iloc[0]


# ----------------------------------------------------------- endpoints ---

ENDPOINTS = {
    "/health": "server status",
    "/stations": "list stations (optional: q=<name substring>, limit=<n>)",
    "/station_availability": "station_id=<id>, time=<ISO datetime, default now>",
}


@app.get("/")
def index():
    return jsonify({"endpoints": ENDPOINTS})


@app.get("/health")
def health():
    return jsonify({"status": "ok", "trips_loaded": len(load_trips())})


@app.get("/stations")
def stations():
    df = load_stations()
    q = request.args.get("q")
    if q:
        df = df[df["name"].str.contains(q, case=False, na=False)]
    limit = request.args.get("limit", type=int)
    if limit:
        df = df.head(limit)
    return jsonify({"count": len(df), "stations": df.to_dict(orient="records")})


@app.get("/station_availability")
def station_availability():
    station = require_station(request.args.get("station_id"))
    when = parse_time(request.args.get("time"))
    sid = station["station_id"]

    trips = load_trips()
    departures = trips.loc[trips["start_station_id"] == sid, "started_at"]
    arrivals = trips.loc[trips["end_station_id"] == sid, "ended_at"]

    # Historical average for the same weekday + hour across the dataset,
    # divided by how many such weekdays the data covers.
    weekday_count = int((dataset_days().weekday == when.weekday()).sum()) or 1

    def avg_per_slot(times: pd.Series) -> float:
        same_slot = times[(times.dt.weekday == when.weekday()) & (times.dt.hour == when.hour)]
        return round(len(same_slot) / weekday_count, 2)

    avg_dep = avg_per_slot(departures)
    avg_arr = avg_per_slot(arrivals)
    net = round(avg_arr - avg_dep, 2)

    if net > 0.5:
        outlook = "filling up (more bikes arriving than leaving)"
    elif net < -0.5:
        outlook = "emptying (more bikes leaving than arriving)"
    else:
        outlook = "stable"

    # Actual counts for that exact hour, if the date is covered by the data.
    hour_start = pd.Timestamp(when).floor("h")
    hour_end = hour_start + pd.Timedelta(hours=1)
    actual = None
    if trips["started_at"].min() <= hour_start <= trips["started_at"].max():
        actual = {
            "departures": int(((departures >= hour_start) & (departures < hour_end)).sum()),
            "arrivals": int(((arrivals >= hour_start) & (arrivals < hour_end)).sum()),
        }

    return jsonify({
        "station": {
            "station_id": sid,
            "name": station["name"],
            "lat": float(station["lat"]),
            "lng": float(station["lng"]),
        },
        "time": when.isoformat(),
        "weekday": when.strftime("%A"),
        "hour": when.hour,
        "historical_avg_per_hour": {
            "departures": avg_dep,
            "arrivals": avg_arr,
            "net_flow": net,
        },
        "outlook": outlook,
        "actual_in_hour": actual,
    })


if __name__ == "__main__":
    print("Loading data...")
    # load_stations()
    app.run(host="127.0.0.1", port=5000, debug=True)
