#!/usr/bin/env python3
"""Local server for the SWIFT landing page, plus the forecast API behind its map.

Usage:
    python3 server.py            # http://localhost:8000
    python3 server.py --port 5050
    python3 server.py --open     # also opens the browser

API:
    GET /api/forecast?day=weekday|weekend&time=HH:MM[&threshold=2]

    Takes the live Citi Bike GBFS snapshot (bike counts right now), applies the
    average hourly net flow from ../data/data.json for the hour starting at
    `time` on a `day` day, and returns every station with its expected bike
    count and status ("low" = likely to empty, "high" = likely to overflow,
    "medium" = fine). The forecast math is ../forecast.py, the same module the
    Streamlit app uses. Missing parameters default to the current New York time
    and day type.

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import csv
import functools
import gzip
import http.server
import json
import logging
import socketserver
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
sys.path.insert(0, str(PROJECT))

from forecast import (  # noqa: E402  (needs the project folder on sys.path)
    DAY_TYPES,
    DEFAULT_THRESHOLD,
    NEW_YORK,
    THRESHOLD_RANGE,
    day_type,
    predict_station_availability,
)

HISTORY_PATH = PROJECT / "data" / "data.json"
BACKUP_FILE = PROJECT / "fallback_feed.csv"   # same backup file feed.py writes
GBFS_DISCOVERY_URL = "https://gbfs.citibikenyc.com/gbfs/gbfs.json"
SNAPSHOT_TTL = 60                             # seconds, same as feed.py's cache
FORECAST_HORIZON = timedelta(hours=1)

INFO_COLUMNS = ["station_id", "short_name", "name", "lat", "lon", "capacity"]
STATUS_COLUMNS = ["station_id", "num_bikes_available", "num_docks_available",
                  "is_installed", "is_renting", "is_returning"]
COLUMNS = INFO_COLUMNS + STATUS_COLUMNS[1:] + ["last_updated"]

logger = logging.getLogger("swift-landing")


# ------------------------------------------------------------- history ---

def load_history(path: Path = HISTORY_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        history = json.load(handle)
    for section in ("meta", *DAY_TYPES):
        if not isinstance(history.get(section), dict):
            raise ValueError(f"{path}: missing or invalid '{section}' section")
    return history


def station_hourly_flows(history: dict, short_name: Any) -> tuple[dict[tuple[str, int], float], bool]:
    """(day_type, hour) -> net flow for one station, plus a 'no history' flag (as in app.py)."""
    flows: dict[tuple[str, int], float] = {}
    found = False
    for kind in DAY_TYPES:
        hours = history[kind].get(short_name) if isinstance(short_name, str) else None
        found = found or hours is not None
        for hour in range(24):
            flows[(kind, hour)] = float((hours or {}).get(str(hour), 0.0))
    return flows, not found


# ------------------------------------------------------------ live feed ---

def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "swift-landing/1.0"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # drop NaN


def _in_service(row: dict) -> bool:
    return _number(row.get("is_installed")) == 1 and (_number(row.get("capacity")) or 0) > 0


def fetch_live() -> list[dict]:
    """station_information joined with station_status on station_id, in-service stations only."""
    discovery = _get_json(GBFS_DISCOVERY_URL)
    feeds = {feed["name"]: feed["url"] for feed in discovery["data"]["en"]["feeds"]}
    info = _get_json(feeds["station_information"])
    status = _get_json(feeds["station_status"])

    by_id = {str(s["station_id"]): {k: s.get(k) for k in STATUS_COLUMNS} for s in status["data"]["stations"]}
    rows = []
    for station in info["data"]["stations"]:
        sid = str(station["station_id"])
        if sid not in by_id:
            continue
        row = {k: station.get(k) for k in INFO_COLUMNS}
        row.update(by_id[sid])
        row["station_id"] = sid
        row["last_updated"] = status["last_updated"]
        if _in_service(row):
            rows.append(row)
    return rows


def save_backup(rows: list[dict]) -> None:
    with BACKUP_FILE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_backup() -> list[dict]:
    try:
        with BACKUP_FILE.open(newline="", encoding="utf-8") as handle:
            return [row for row in csv.DictReader(handle) if _in_service(row)]
    except OSError as error:
        logger.error("Could not read backup %s: %s", BACKUP_FILE, error)
        return []


class Snapshot:
    """Live stations, cached for SNAPSHOT_TTL seconds; falls back to the backup CSV."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fetched = 0.0
        self._rows: list[dict] = []
        self._is_backup = False

    def get(self) -> tuple[list[dict], bool]:
        with self._lock:
            if time.monotonic() - self._fetched > SNAPSHOT_TTL or not self._rows:
                try:
                    self._rows, self._is_backup = fetch_live(), False
                    save_backup(self._rows)
                except Exception as error:  # network down, feed changed, ...
                    logger.error("Live feed failed (%s); using backup %s", error, BACKUP_FILE.name)
                    self._rows, self._is_backup = load_backup(), True
                self._fetched = time.monotonic()
            return self._rows, self._is_backup


# ------------------------------------------------------------- forecast ---

def window_start(kind: str, hours: int, minutes: int) -> datetime:
    """The chosen clock time on the next date (from today, New York) of the chosen day type."""
    day: date = datetime.now(NEW_YORK).date()
    while day_type(day) != kind:
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, hours, minutes, tzinfo=NEW_YORK)


def build_forecast(history: dict, snapshot: Snapshot, query: dict[str, list[str]]) -> dict:
    now = datetime.now(NEW_YORK)

    kind = (query.get("day") or [day_type(now)])[0]
    if kind not in DAY_TYPES:
        raise ValueError(f"day must be one of {', '.join(DAY_TYPES)}")

    raw_time = (query.get("time") or [now.strftime("%H:%M")])[0]
    try:
        hours, minutes = (int(part) for part in raw_time.split(":"))
        if not (0 <= hours < 24 and 0 <= minutes < 60):
            raise ValueError
    except ValueError:
        raise ValueError("time must be HH:MM (24-hour)") from None

    try:
        threshold = float((query.get("threshold") or [DEFAULT_THRESHOLD])[0])
    except ValueError:
        raise ValueError("threshold must be a number") from None
    threshold = min(max(threshold, THRESHOLD_RANGE[0]), THRESHOLD_RANGE[1])

    start = window_start(kind, hours, minutes)
    end = start + FORECAST_HORIZON
    rows, is_backup = snapshot.get()

    stations, skipped = [], 0
    counts = {"low": 0, "high": 0, "medium": 0, "no_history": 0}
    as_of = None
    for row in rows:
        try:
            lat, lon = _number(row.get("lat")), _number(row.get("lon"))
            bikes, capacity = _number(row.get("num_bikes_available")), _number(row.get("capacity"))
            if None in (lat, lon, bikes, capacity):
                raise ValueError("missing coordinates or counts")
            flows, no_history = station_hourly_flows(history, row.get("short_name"))
            result = predict_station_availability(
                num_bikes_available=bikes,
                capacity=capacity,
                current_time=start,
                target_time=end,
                hourly_flows=flows,
                threshold=threshold,
            )
        except Exception as error:  # one bad station must never break the map
            skipped += 1
            logger.debug("Skipped station %s: %s", row.get("station_id"), error)
            continue

        stamp = _number(row.get("last_updated"))
        if stamp is not None:
            as_of = max(as_of or stamp, stamp)
        counts[result["status"]] += 1
        counts["no_history"] += no_history
        stations.append({
            "id": row["station_id"],
            "name": row.get("name") or "Unnamed station",
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "capacity": int(capacity),
            "bikes": int(bikes),
            "docks": int(_number(row.get("num_docks_available")) or 0),
            "expected": round(result["expected"], 1),
            "bounded": round(result["bounded_expected"], 1),
            "net_flow": round(result["net_flow"], 2),
            "status": result["status"],
            "no_history": no_history,
        })

    meta = history["meta"]
    return {
        "day": kind,
        "time": f"{hours:02d}:{minutes:02d}",
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "threshold": threshold,
        "as_of": datetime.fromtimestamp(as_of, NEW_YORK).isoformat() if as_of else None,
        "is_backup": is_backup,
        "counts": {**counts, "skipped": skipped},
        "history": {
            "first_day": meta.get("first_day"),
            "last_day": meta.get("last_day"),
            "days": meta.get("days", {}),
        },
        "stations": stations,
    }


# --------------------------------------------------------------- server ---

class Handler(http.server.SimpleHTTPRequestHandler):
    history: dict = {}
    snapshot: Snapshot

    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".woff2": "font/woff2",
        ".woff": "font/woff",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
    }

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/api/forecast":
            self._forecast(parse_qs(url.query))
        elif url.path.startswith("/api/"):
            self._send_json({"error": "not found"}, 404)
        else:
            super().do_GET()

    def _forecast(self, query: dict[str, list[str]]) -> None:
        try:
            self._send_json(build_forecast(self.history, self.snapshot, query))
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)
        except Exception:
            logger.exception("Forecast failed")
            self._send_json({"error": "forecast failed; see the server log"}, 500)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        gzipped = "gzip" in self.headers.get("Accept-Encoding", "") and len(body) > 1024
        if gzipped:
            body = gzip.compress(body, compresslevel=5)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if gzipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Always serve fresh files while developing.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the SWIFT landing page and its forecast API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="open the page in a browser")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        Handler.history = load_history()
    except (OSError, ValueError) as error:
        sys.exit(f"Cannot start: {HISTORY_PATH} is missing or invalid ({error}). "
                 "Build it with `python data/analyze_data.py`, then restart.")
    Handler.snapshot = Snapshot()

    handler = functools.partial(Handler, directory=str(ROOT))
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    with socketserver.ThreadingTCPServer((args.host, args.port), handler) as httpd:
        url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}/"
        print(f"SWIFT landing → {url}   (map page: {url}map.html, API: {url}api/forecast)\nCtrl+C to stop.")
        if args.open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
