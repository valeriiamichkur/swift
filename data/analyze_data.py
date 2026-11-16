"""Дані 1: поїздки Citi Bike -> таблиця типового потоку (data.json).

Запуск з кореня проєкту:  python data/analyze_data.py
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # щоб імпортувати forecast.py з кореня проєкту

from forecast import DAY_TYPES, day_type  # noqa: E402  одне правило будні/вихідні на весь проєкт

NY_TZ = "America/New_York"
USECOLS = ["started_at", "ended_at", "start_station_id", "end_station_id"]

# Лише повні дні: 31.08 має 64 поїздки за 5 годин, 14.09 обривається о 19:59.
FIRST_DAY = "2026-09-01"
LAST_DAY = "2026-09-13"
# Святкові дні їздять як вихідні, тож не змішуємо їх із буднями.
EXCLUDED_DAYS = {"2026-09-07": "Labor Day"}


def load_trips(path):
    """1. Завантаження: читає CSV лише з 4 потрібних колонок; ID станцій — як текст."""
    return pd.read_csv(path, usecols=USECOLS, dtype={"start_station_id": str, "end_station_id": str})


def _to_ny(series):
    """Перетворює текст у час Нью-Йорка (мітки без поясу вважає локальними)."""
    ts = pd.to_datetime(series, format="mixed", errors="coerce")
    if ts.dt.tz is None:
        return ts.dt.tz_localize(NY_TZ, ambiguous="NaT", nonexistent="NaT")
    return ts.dt.tz_convert(NY_TZ)


def clean_trips(df):
    """2-3. Очищення: переводить час у NY. Порожні ID станцій відкидаються пізніше,
    окремо для відправлень і прибуттів, щоб не губити другу половину поїздки."""
    df = df.copy()
    df["started_at"] = _to_ny(df["started_at"])
    df["ended_at"] = _to_ny(df["ended_at"])
    return df


def history_days(first_day=FIRST_DAY, last_day=LAST_DAY, excluded=EXCLUDED_DAYS):
    """Дні, з яких рахуємо середні: діапазон без виключених дат."""
    days = pd.date_range(first_day, last_day, freq="D").date
    skip = {date.fromisoformat(d) for d in excluded}
    return [d for d in days if d not in skip]


def _events(df, time_col, station_col, day_types):
    """Таблиця подій: станція, година, тип дня — лише для дат із day_types."""
    ts = df[time_col]
    events = pd.DataFrame({
        "station": df[station_col].values,
        "hour": ts.dt.hour.values,
        "daytype": ts.dt.date.map(day_types).values,
    })
    return events.dropna(subset=["station", "daytype"])


def build_flow_table(df, days):
    """4. Агрегація: station, hour, daytype, departures, arrivals, net_flow.
    Усе усереднено на один день: net_flow = arrivals - departures."""
    day_types = {d: day_type(d) for d in days}
    dep = _events(df, "started_at", "start_station_id", day_types)
    arr = _events(df, "ended_at", "end_station_id", day_types)

    # скільки днів кожного типу у вибраному періоді (рахуємо з календаря, а не з даних)
    n_days = pd.Series(list(day_types.values())).value_counts()

    keys = ["station", "hour", "daytype"]
    dep_n = dep.groupby(keys).size().rename("departures")
    arr_n = arr.groupby(keys).size().rename("arrivals")

    # повна сітка станція x година x тип дня; відсутні комірки = 0
    stations = pd.concat([dep["station"], arr["station"]]).unique()
    grid = pd.MultiIndex.from_product([stations, range(24), list(DAY_TYPES)], names=keys)
    flow = pd.concat([dep_n, arr_n], axis=1).reindex(grid).fillna(0).reset_index()

    days_per_type = flow["daytype"].map(n_days).fillna(1)
    flow["departures"] = flow["departures"] / days_per_type
    flow["arrivals"] = flow["arrivals"] / days_per_type
    flow["net_flow"] = flow["arrivals"] - flow["departures"]
    return flow


def make_flow_table(path, days):
    """Весь конвеєр одним викликом: CSV -> таблиця потоку за вибрані дні."""
    return build_flow_table(clean_trips(load_trips(path)), days)


def history_meta(days, excluded=EXCLUDED_DAYS):
    """Опис періоду для застосунку: межі, кількість днів кожного типу, виключені дати."""
    counts = pd.Series([day_type(d) for d in days]).value_counts()
    return {
        "first_day": min(days).isoformat(),
        "last_day": max(days).isoformat(),
        "days": {t: int(counts.get(t, 0)) for t in DAY_TYPES},
        "excluded": excluded,
    }


def flow_to_dict(flow, meta, min_abs=0.005):
    """Перетворює таблицю потоку на вкладений словник:
    {"meta": {...}, daytype: {station_id: {hour(str): net_flow}}}.
    Години з нульовим потоком пропускаємо (у споживача це .get(hour, 0))."""
    flow = flow.copy()
    flow["net_flow"] = flow["net_flow"].round(2)
    flow = flow[flow["net_flow"].abs() >= min_abs]  # викидаємо нулі

    result = {"meta": meta, **{t: {} for t in DAY_TYPES}}
    for row in flow.itertuples(index=False):
        station_hours = result[row.daytype].setdefault(row.station, {})
        station_hours[str(int(row.hour))] = float(row.net_flow)
    return result


def save_flow_json(flow, meta, path):
    """Зберігає словник потоку у JSON-файл."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flow_to_dict(flow, meta), f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    days = history_days()
    table = make_flow_table(HERE / "raw_data.csv", days)
    meta = history_meta(days)
    print(table.head())
    print(table.shape, meta)
    save_flow_json(table, meta, HERE / "data.json")
    print("Готово: data.json,", table["station"].nunique(), "станцій")
