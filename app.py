"""Streamlit entry point: live Citi Bike stations at risk of emptying or overflowing in the next hour.

Run with:  streamlit run app.py
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from charts import TABLE_COLUMNS, build_risk_tables, map_points
from feed import load_live_snapshot
from forecast import (
    DAY_TYPES,
    DEFAULT_THRESHOLD,
    NEW_YORK,
    THRESHOLD_RANGE,
    predict_station_availability,
)
from station_map import render_station_map


# --------------------------------------------------------------- settings ---

HISTORY_PATH = Path(__file__).parent / "data" / "data.json"

# Matches the ttl of feed.load_live_snapshot's cache.
REFRESH_SECONDS = 60

FORECAST_HORIZON = timedelta(hours=1)

TIME_FORMAT = "%Y-%m-%d %H:%M %Z"

logger = logging.getLogger("app")

History = dict[str, Any]


# ------------------------------------------------------- user-facing text ---
# Stand-in for ui_text.py, which does not exist yet. Move these there when it does.

TEXT = {
    "page_title": "Citi Bike: stations at risk in the next hour",
    "disclaimer": (
        "Naive estimate: expected bikes in 1 h = bikes now + average net flow for the coming hour, "
        "from {weekday} weekdays and {weekend} weekend days of trip history ({first_day} to {last_day}). "
        "Not a guarantee."
    ),
    "history_error": (
        "Cannot start: {path} is missing or invalid ({error}). "
        "Build it with `python data/analyze_data.py`, then restart."
    ),
    "threshold_label": "Risk threshold (bikes)",
    "threshold_help": (
        "Flag a station as likely to empty when it is expected to have at most this many bikes, "
        "and as likely to overflow when it is expected to have at most this many free docks."
    ),
    "last_updated": "Station data as of {as_of} · forecast for {target}",
    "unknown_time": "unknown",
    "backup_notice": "Live feed unavailable: showing backup data from {as_of}.",
    "no_data": "No station data available: both the live feed and the backup file failed.",
    "metric_low": "Likely to empty",
    "metric_high": "Likely to overflow",
    "metric_no_history": "No history (flow = 0)",
    "metric_skipped": "Skipped (bad data)",
    "map_title": "Map",
    # Colour names must match station_map.STATUS_COLORS.
    "map_legend": "Vermillion: likely to empty · Blue: likely to overflow · Grey: fine",
    "low_title": "Top 10 most likely to run out of bikes",
    "high_title": "Top 10 most likely to overflow",
    "empty_table": "No stations in this group right now.",
    "tables_error": "Could not build the risk tables; see the server log.",
    "all_stations": "All stations",
    "col_status": "Status",
    "col_no_history": "No History",
}


# ---------------------------------------------------------------- startup ---

@st.cache_resource
def configure_logging() -> None:
    """Send log records to the console, once per server process."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@st.cache_resource
def load_history(path: Path = HISTORY_PATH) -> History:
    """Read data.json once per server process and check its top-level shape."""
    with path.open(encoding="utf-8") as handle:
        history = json.load(handle)
    if not isinstance(history, dict):
        raise ValueError("top level must be an object")
    for section in ("meta", *DAY_TYPES):
        if not isinstance(history.get(section), dict):
            raise ValueError(f"missing or invalid '{section}' section")
    return history


def history_or_stop() -> History:
    """Return the history, or show a one-line error and halt the page if it can't be loaded."""
    try:
        return load_history()
    except (OSError, ValueError) as error:
        shown_path = HISTORY_PATH.relative_to(Path(__file__).parent)
        reason = getattr(error, "strerror", None) or error
        message = TEXT["history_error"].format(path=shown_path, error=reason)
        logger.error(message)
        st.error(message)
        st.stop()


# ------------------------------------------------------------- feed times ---

def feed_as_of(stations: pd.DataFrame) -> datetime | None:
    """Time of the GBFS snapshot, from the feed's last_updated column (Unix seconds)."""
    if "last_updated" not in stations:
        return None
    stamps = pd.to_numeric(stations["last_updated"], errors="coerce")
    if stamps.isna().all():
        return None
    return datetime.fromtimestamp(float(stamps.max()), tz=NEW_YORK)


def format_time(moment: datetime | None) -> str:
    """Render a timestamp for display, or the 'unknown' label."""
    return moment.strftime(TIME_FORMAT) if moment else TEXT["unknown_time"]


# ------------------------------------------------------- history lookup ---
# data.json is keyed by the trip data's station ID, which is the feed's short_name.

def station_hourly_flows(history: History, short_name: Any) -> tuple[dict[tuple[str, int], float], bool]:
    """Build the (day_type, hour) -> net_flow map forecast.py expects, plus a 'no history' flag."""
    flows: dict[tuple[str, int], float] = {}
    found = False
    for day_type in DAY_TYPES:
        hours = history[day_type].get(short_name) if isinstance(short_name, str) else None
        found = found or hours is not None
        for hour in range(24):
            flows[(day_type, hour)] = float((hours or {}).get(str(hour), 0.0))
    return flows, not found


# ------------------------------------------------------------- forecasting ---

def forecast_station(
    station: dict[str, Any],
    history: History,
    now: datetime,
    threshold: float,
) -> dict[str, Any]:
    """Run forecast.py for one live station and merge its output into the station row."""
    flows, no_history = station_hourly_flows(history, station.get("short_name"))
    result = predict_station_availability(
        num_bikes_available=station["num_bikes_available"],
        capacity=station["capacity"],
        current_time=now,
        target_time=now + FORECAST_HORIZON,
        hourly_flows=flows,
        threshold=threshold,
    )
    return {**station, **result, "no_history": no_history}


def forecast_all(
    stations: pd.DataFrame,
    history: History,
    now: datetime,
    threshold: float,
) -> tuple[list[dict[str, Any]], int]:
    """Forecast every station, logging and skipping any that fail; return rows and skip count."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for station in stations.to_dict(orient="records"):
        try:
            rows.append(forecast_station(station, history, now, threshold))
        except Exception as error:  # one bad station must never break the page
            skipped += 1
            logger.warning("Skipped station %s (%s): %s", station.get("station_id"), station.get("name"), error)
    logger.info("Forecast %d stations, skipped %d", len(rows), skipped)
    return rows, skipped


def risk_tables(rows: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Build the two top-10 tables with charts.py, or None if that fails."""
    try:
        return build_risk_tables(rows, limit=10)
    except Exception:
        logger.exception("build_risk_tables failed")
        return None


# ------------------------------------------------------------------- views ---

def show_header(meta: dict[str, Any]) -> None:
    """Page title and the naive-estimate disclaimer, worded from data.json's metadata."""
    st.title(TEXT["page_title"])
    days = meta.get("days", {})
    st.info(TEXT["disclaimer"].format(
        weekday=days.get("weekday", "?"),
        weekend=days.get("weekend", "?"),
        first_day=meta.get("first_day", "?"),
        last_day=meta.get("last_day", "?"),
    ))


def threshold_slider() -> float:
    """Risk threshold chosen by the user, with forecast.py's default and range."""
    low, high = THRESHOLD_RANGE
    return st.slider(
        TEXT["threshold_label"],
        min_value=low,
        max_value=high,
        value=DEFAULT_THRESHOLD,
        help=TEXT["threshold_help"],
    )


def show_status_line(as_of: datetime | None, now: datetime, is_backup: bool) -> None:
    """Last-updated time, forecast target time and the backup-data notice."""
    st.caption(TEXT["last_updated"].format(as_of=format_time(as_of), target=format_time(now + FORECAST_HORIZON)))
    if is_backup:
        st.warning(TEXT["backup_notice"].format(as_of=format_time(as_of)))


def show_metrics(rows: list[dict[str, Any]], skipped: int) -> None:
    """Headline counts for the current snapshot."""
    columns = st.columns(4)
    columns[0].metric(TEXT["metric_low"], sum(row["status"] == "low" for row in rows))
    columns[1].metric(TEXT["metric_high"], sum(row["status"] == "high" for row in rows))
    columns[2].metric(TEXT["metric_no_history"], sum(row["no_history"] for row in rows))
    columns[3].metric(TEXT["metric_skipped"], skipped)


def show_map(rows: list[dict[str, Any]]) -> None:
    """Every station as a dot coloured by status, drawn by station_map.py."""
    render_station_map(map_points(rows), TEXT["map_title"], TEXT["map_legend"])


def show_table(title: str, table: pd.DataFrame) -> None:
    """One titled risk table, or an 'empty' note."""
    st.subheader(title)
    if table.empty:
        st.caption(TEXT["empty_table"])
    else:
        st.dataframe(table, hide_index=True, width="stretch")


def show_risk_tables(rows: list[dict[str, Any]]) -> None:
    """The two top-10 tables side by side."""
    tables = risk_tables(rows)
    if tables is None:
        st.error(TEXT["tables_error"])
        return
    low_table, high_table = tables
    left, right = st.columns(2)
    with left:
        show_table(TEXT["low_title"], low_table)
    with right:
        show_table(TEXT["high_title"], high_table)


def show_all_stations(rows: list[dict[str, Any]]) -> None:
    """Full result list, collapsed by default."""
    labels = {**TABLE_COLUMNS, "status": TEXT["col_status"], "no_history": TEXT["col_no_history"]}
    table = pd.DataFrame(rows, columns=list(labels)).rename(columns=labels)
    with st.expander(TEXT["all_stations"]):
        st.dataframe(table, hide_index=True, width="stretch")


# -------------------------------------------------------------------- page ---

@st.fragment(run_every=REFRESH_SECONDS)
def dashboard(history: History, threshold: float) -> None:
    """Fetch, forecast and render; Streamlit reruns this every REFRESH_SECONDS."""
    now = datetime.now(NEW_YORK)
    stations, is_backup = load_live_snapshot()
    show_status_line(feed_as_of(stations), now, is_backup)
    if stations.empty:
        st.error(TEXT["no_data"])
        return
    rows, skipped = forecast_all(stations, history, now, threshold)
    show_metrics(rows, skipped)
    show_map(rows)
    show_risk_tables(rows)
    show_all_stations(rows)


def main() -> None:
    """Configure logging, load the history once, then render the self-refreshing dashboard."""
    configure_logging()
    st.set_page_config(page_title=TEXT["page_title"], layout="wide")
    history = history_or_stop()
    show_header(history["meta"])
    dashboard(history, threshold_slider())


main()
