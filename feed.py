import logging
import requests
import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)

GBFS_DISCOVERY_URL = "https://gbfs.citibikenyc.com/gbfs/gbfs.json"

@st.cache_data(ttl=60)
def load_live_data():
    """
    Завантажує живі дані Citi Bike через GBFS API,
    об'єднує station_information та station_status за station_id.
    Має fallback на локальний файл, якщо API недоступне.
    """
    try:
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
        
        stations_info = pd.DataFrame(info_res.json()['data']['stations'])
        stations_status = pd.DataFrame(status_res.json()['data']['stations'])
        
        stations_info = stations_info[['station_id', 'name', 'lat', 'lon', 'capacity']]
        stations_status = stations_status[['station_id', 'num_bikes_available', 'num_docks_available']]
        
        stations_info['station_id'] = stations_info['station_id'].astype(str)
        stations_status['station_id'] = stations_status['station_id'].astype(str)
        
        df = pd.merge(stations_info, stations_status, on='station_id', how='inner')
        df.to_csv("fallback_feed.csv", index=False)
        
        return df

    except Exception as e:
        logger.error(f"Помилка при завантаженні живих даних: {e}. Спроба завантажити бекап...")
        try:
            fallback_df = pd.read_csv("fallback_feed.csv", dtype={'station_id': str})
            return fallback_df
        except Exception as fallback_error:
            logger.error(f"Не вдалося завантажити бекап: {fallback_error}")
            return pd.DataFrame(columns=[
                'station_id', 'name', 'lat', 'lon', 
                'capacity', 'num_bikes_available', 'num_docks_available'
            ])


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
