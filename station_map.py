"""Station map: how forecast points are drawn (colours, sizes, the Streamlit map element)."""

import pandas as pd
import streamlit as st


# ----------------------------------------------------------------- styling ---

# Okabe-Ito colours: distinguishable with the common forms of colour blindness.
STATUS_COLORS = {
    "low": "#D55E00",     # vermillion: likely to run out of bikes
    "high": "#0072B2",    # blue: likely to overflow
    "medium": "#999999",  # grey: fine
}

POINT_SIZE = 40  # metres


def style_points(points: pd.DataFrame) -> pd.DataFrame:
    """Add a color and size column to each point; points with an unknown status are dropped."""
    styled = points[points["status"].isin(STATUS_COLORS)].copy()
    styled["color"] = styled["status"].map(STATUS_COLORS)
    styled["size"] = POINT_SIZE
    return styled


# --------------------------------------------------------------- rendering ---

def render_station_map(points: pd.DataFrame, title: str, legend: str) -> None:
    """Draw the titled map with its legend; points need lat, lon and status columns."""
    st.subheader(title)
    st.caption(legend)
    st.map(style_points(points), latitude="lat", longitude="lon", color="color", size="size")
