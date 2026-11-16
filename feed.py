import logging
from pathlib import Path

import requests
import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

GBFS_DISCOVERY_URL = "https://gbfs.citibikenyc.com/gbfs/gbfs.json"

# Бекап лежить поруч із цим файлом, незалежно від папки, з якої запущено застосунок.
BACKUP_FILE = Path(__file__).parent / "fallback_feed.csv"

# short_name — це той самий ID станції, що й start/end_station_id у даних поїздок.
INFO_COLUMNS = ['station_id', 'short_name', 'name', 'lat', 'lon', 'capacity']
STATUS_COLUMNS = [
    'station_id', 'num_bikes_available', 'num_docks_available',
    'is_installed', 'is_renting', 'is_returning',
]
COLUMNS = INFO_COLUMNS + STATUS_COLUMNS[1:] + ['last_updated']

# ID читаємо як текст, інакше pandas перетворить "6593.10" на число 6593.1.
ID_DTYPES = {'station_id': str, 'short_name': str}


def _fetch_live():
    """Завантажує живі дані GBFS і об'єднує station_information та station_status за station_id."""
    discovery_res = requests.get(GBFS_DISCOVERY_URL, timeout=10)
    discovery_res.raise_for_status()
    data = discovery_res.json()

    feeds = {feed['name']: feed['url'] for feed in data['data']['en']['feeds']}
    info_url = feeds.get('station_information')
    status_url = feeds.get('station_status')

    if not info_url or not status_url:
        raise ValueError("Не вдалося знайти необхідні URL у GBFS каталозі.")

    info_res = requests.get(info_url, timeout=10)
    status_res = requests.get(status_url, timeout=10)

    info_res.raise_for_status()
    status_res.raise_for_status()

    status_json = status_res.json()

    stations_info = pd.DataFrame(info_res.json()['data']['stations']).reindex(columns=INFO_COLUMNS)
    stations_status = pd.DataFrame(status_json['data']['stations']).reindex(columns=STATUS_COLUMNS)

    stations_info['station_id'] = stations_info['station_id'].astype(str)
    stations_status['station_id'] = stations_status['station_id'].astype(str)

    df = pd.merge(stations_info, stations_status, on='station_id', how='inner')
    df['last_updated'] = status_json['last_updated']  # час знімка GBFS, секунди Unix
    return _in_service(df)


def _in_service(df):
    """Лишає лише встановлені станції з ненульовою місткістю (решта не працює)."""
    return df[(df['is_installed'] == 1) & (df['capacity'] > 0)].reset_index(drop=True)


def _load_backup():
    """Читає останній збережений знімок; бракуючі колонки (старий формат) заповнює порожніми."""
    try:
        return pd.read_csv(BACKUP_FILE, dtype=ID_DTYPES).reindex(columns=COLUMNS)
    except Exception as fallback_error:
        logger.error(f"Не вдалося завантажити бекап: {fallback_error}")
        return pd.DataFrame(columns=COLUMNS)


@st.cache_data(ttl=60)
def load_live_snapshot():
    """
    Повертає (df, is_backup): живі дані Citi Bike і прапорець,
    чи це дані з локального бекапу, бо API недоступне.
    """
    try:
        df = _fetch_live()
        df.to_csv(BACKUP_FILE, index=False)
        return df, False
    except Exception as e:
        logger.error(f"Помилка при завантаженні живих даних: {e}. Спроба завантажити бекап...")
        return _load_backup(), True


def load_live_data():
    """Лише таблиця станцій, без прапорця бекапу (для зворотної сумісності)."""
    return load_live_snapshot()[0]


def get_available_bikes(station_id: str, df: pd.DataFrame = None):
    """
    Повертає актуальну кількість велосипедів на станції (зайнятих слотів) за її station_id.
    Якщо таблицю df не передано, автоматично підтягує свіжі (або кешовані) дані.
    Повертає int або None, якщо станцію не знайдено.
    """
    if df is None:
        df = load_live_data()

    match = df[df['station_id'].astype(str) == str(station_id)]

    if match.empty:
        return None

    return int(match.iloc[0]['num_bikes_available'])
