"""Дані 1: тиждень поїздок Citi Bike -> таблиця типового потоку."""
import json

import numpy as np
import pandas as pd

NY_TZ = "America/New_York"
USECOLS = ["started_at", "ended_at", "start_station_name", "end_station_name"]


def load_trips(path):
    """1. Завантаження: читає CSV лише з 4 потрібних колонок."""
    return pd.read_csv(path, usecols=USECOLS)


def _to_ny(series):
    """Перетворює текст у час Нью-Йорка (мітки без поясу вважає локальними)."""
    ts = pd.to_datetime(series, format="mixed", errors="coerce")
    if ts.dt.tz is None:
        return ts.dt.tz_localize(NY_TZ, ambiguous="NaT", nonexistent="NaT")
    return ts.dt.tz_convert(NY_TZ)


def clean_trips(df):
    """2-3. Очищення: прибирає рядки без назви станції/часу, переводить час у NY."""
    df = df.dropna(subset=USECOLS).copy()
    df["started_at"] = _to_ny(df["started_at"])
    df["ended_at"] = _to_ny(df["ended_at"])
    return df.dropna(subset=["started_at", "ended_at"])


def select_week(df, week_start):
    """Лишає рівно 7 днів від week_start (напр. '2026-10-05', понеділок)."""
    start = pd.Timestamp(week_start, tz=NY_TZ)
    end = start + pd.Timedelta(days=7)
    in_week = (df["started_at"] >= start) & (df["ended_at"] < end)
    return df[in_week]


def _events(df, time_col, station_col):
    """Таблиця подій: станція, година, дата, тип дня (weekday/weekend)."""
    ts = df[time_col]
    return pd.DataFrame({
        "station": df[station_col].values,
        "hour": ts.dt.hour.values,
        "date": ts.dt.date.values,
        "daytype": np.where(ts.dt.day_of_week.values >= 5, "weekend", "weekday"),
    })


def build_flow_table(df):
    """4. Агрегація: station, hour, daytype, departures, arrivals, net_flow.
    Усе усереднено на один день: net_flow = arrivals - departures."""
    dep = _events(df, "started_at", "start_station_name")
    arr = _events(df, "ended_at", "end_station_name")

    # скільки різних днів кожного типу в даних (5 буднів, 2 вихідних)
    n_days = pd.concat([dep, arr]).groupby("daytype")["date"].nunique()

    keys = ["station", "hour", "daytype"]
    dep_n = dep.groupby(keys).size().rename("departures")
    arr_n = arr.groupby(keys).size().rename("arrivals")

    # повна сітка станція x година x тип дня; відсутні комірки = 0
    stations = pd.concat([dep["station"], arr["station"]]).unique()
    grid = pd.MultiIndex.from_product(
        [stations, range(24), ["weekday", "weekend"]], names=keys)
    flow = pd.concat([dep_n, arr_n], axis=1).reindex(grid).fillna(0).reset_index()

    days = flow["daytype"].map(n_days).fillna(1)
    flow["departures"] = flow["departures"] / days
    flow["arrivals"] = flow["arrivals"] / days
    flow["net_flow"] = flow["arrivals"] - flow["departures"]
    return flow


def make_flow_table(path, week_start):
    """Весь конвеєр одним викликом: CSV -> таблиця потоку за тиждень."""
    trips = select_week(clean_trips(load_trips(path)), week_start)
    return build_flow_table(trips)


def flow_to_dict(flow, min_abs=0.005):
    """Перетворює таблицю потоку на вкладений словник:
    {daytype: {station: {hour(str): net_flow}}}.
    Години з нульовим потоком пропускаємо (у споживача це .get(hour, 0))."""
    flow = flow.copy()
    flow["net_flow"] = flow["net_flow"].round(2)
    flow = flow[flow["net_flow"].abs() >= min_abs]  # викидаємо нулі

    result = {"weekday": {}, "weekend": {}}
    for row in flow.itertuples(index=False):
        station_hours = result[row.daytype].setdefault(row.station, {})
        station_hours[str(int(row.hour))] = float(row.net_flow)
    return result


def save_flow_json(flow, path="flow.json"):
    """Зберігає словник потоку у JSON-файл."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flow_to_dict(flow), f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    from pathlib import Path

    here = Path(__file__).parent
    table = make_flow_table(here / "raw_data.csv", "2026-08-31")
    print(table.head())
    print(table.shape)
    save_flow_json(table, here / "flow.json")
    print("Готово: flow.json,", table["station"].nunique(), "станцій")
