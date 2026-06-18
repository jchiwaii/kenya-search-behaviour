from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path(os.getenv("TRENDS_DB_PATH", "data/search_behaviour.db"))

st.set_page_config(page_title="Kenyan Search Pulse", page_icon="🇰🇪", layout="wide")
st.title("Kenyan Search Pulse")
st.caption("What is surging on Google Search in Kenya — not total search volume")

if not DB_PATH.exists():
    st.info("No data yet. Run `make ingest`, then refresh this page.")
    st.stop()


@st.cache_data(ttl=60)
def load_data(db_path: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    with sqlite3.connect(db_path) as connection:
        runs = pd.read_sql_query(
            "SELECT * FROM ingestion_runs WHERE status = 'success' ORDER BY captured_at DESC",
            connection,
        )
        latest_run_id = runs.iloc[0]["run_id"]
        trends = pd.read_sql_query(
            """
            SELECT t.*, COUNT(n.news_item_id) AS story_count
            FROM run_trends rt
            JOIN trends t ON t.trend_id = rt.trend_id
            LEFT JOIN news_items n ON n.trend_id = t.trend_id
            WHERE rt.run_id = ?
            GROUP BY t.trend_id
            ORDER BY COALESCE(t.traffic_lower_bound, 0) DESC, t.published_at DESC
            """,
            connection,
            params=(latest_run_id,),
        )
        stories = pd.read_sql_query(
            """
            SELECT n.*, t.query
            FROM news_items n
            JOIN trends t ON t.trend_id = n.trend_id
            JOIN run_trends rt ON rt.trend_id = t.trend_id
            WHERE rt.run_id = ?
            ORDER BY t.traffic_lower_bound DESC, t.query, n.position
            """,
            connection,
            params=(latest_run_id,),
        )
    return runs, trends, stories


runs, trends, stories = load_data(str(DB_PATH))
latest = runs.iloc[0]
trends["published_at"] = pd.to_datetime(trends["published_at"], utc=True)

metric_1, metric_2, metric_3, metric_4 = st.columns(4)
metric_1.metric("Current trends", f"{len(trends):,}")
metric_2.metric("Linked stories", f"{len(stories):,}")
metric_3.metric("News sources", f"{stories['source'].nunique():,}")
metric_4.metric("Snapshots collected", f"{len(runs):,}")

st.caption(f"Latest capture: {pd.to_datetime(latest['captured_at']).strftime('%d %b %Y, %H:%M UTC')}")

search = st.text_input("Filter queries", placeholder="e.g. fuel, football, HELB")
view = trends.copy()
if search:
    view = view[view["query"].str.contains(search, case=False, na=False)]

left, right = st.columns([3, 2])
with left:
    st.subheader("Current surge signals")
    display = view[["query", "traffic_label", "published_at", "story_count"]].rename(
        columns={
            "query": "Search query",
            "traffic_label": "Traffic bucket",
            "published_at": "Started trending",
            "story_count": "Stories",
        }
    )
    st.dataframe(display, hide_index=True, width="stretch")

with right:
    st.subheader("Traffic bucket lower bounds")
    chart = view.dropna(subset=["traffic_lower_bound"]).head(12).set_index("query")
    st.bar_chart(chart["traffic_lower_bound"], horizontal=True)
    st.caption("A label such as 500+ is plotted as 500. It is a bucket, not an exact count.")

st.subheader("News context")
if stories.empty:
    st.write("No linked stories in this snapshot.")
else:
    selected_query = st.selectbox("Trend", options=view["query"].tolist()) if not view.empty else None
    if selected_query:
        selected = stories[stories["query"] == selected_query]
        for row in selected.itertuples():
            st.markdown(f"- [{row.title}]({row.url}) — {row.source or 'Unknown source'}")

with st.expander("How to read this dashboard"):
    st.write(
        "Google's Trending now feed highlights queries with a recent surge that are often tied "
        "to a news story. It does not rank the most searched terms overall. Longer-term claims "
        "require repeated snapshots or interest-over-time data from Google Trends Explore/the "
        "official API."
    )
