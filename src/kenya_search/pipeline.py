from __future__ import annotations

import hashlib
import re
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

RSS_URL = "https://trends.google.com/trending/rss?geo={geo}"
HT = "https://trends.google.com/trending/rss"
USER_AGENT = "kenya-search-behaviour/0.1 (research; Google Trends RSS)"


@dataclass(frozen=True)
class ParsedFeed:
    trends: list[dict[str, object]]
    news_items: list[dict[str, object]]


def utc_now() -> datetime:
    return datetime.now(UTC)


def fetch_rss(geo: str = "KE", timeout: int = 30) -> bytes:
    request = urllib.request.Request(
        RSS_URL.format(geo=geo.upper()),
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    if not payload.strip().startswith(b"<?xml"):
        raise ValueError("Google Trends returned a non-XML response")
    return payload


def archive_payload(payload: bytes, raw_dir: Path, geo: str, captured_at: datetime) -> Path:
    partition = raw_dir / "trending" / f"geo={geo.upper()}" / captured_at.strftime("%Y-%m-%d")
    partition.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()[:12]
    path = partition / f"{captured_at.strftime('%Y%m%dT%H%M%SZ')}_{digest}.xml"
    path.write_bytes(payload)
    return path


def parse_traffic_lower_bound(label: str | None) -> int | None:
    if not label:
        return None
    match = re.search(r"([\d,.]+)", label)
    if not match:
        return None
    return int(match.group(1).replace(",", "").replace(".", ""))


def _text(node: ET.Element, path: str, default: str = "") -> str:
    value = node.findtext(path, default=default)
    return value.strip() if value else default


def _iso_pub_date(value: str) -> str:
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def parse_rss(payload: bytes, geo: str = "KE") -> ParsedFeed:
    root = ET.fromstring(payload)
    trends: list[dict[str, object]] = []
    news_items: list[dict[str, object]] = []

    for item in root.findall("./channel/item"):
        title = _text(item, "title")
        pub_date = _iso_pub_date(_text(item, "pubDate"))
        traffic_label = _text(item, f"{{{HT}}}approx_traffic")
        identity = f"{geo.upper()}|{title.casefold()}|{pub_date}"
        trend_id = hashlib.sha256(identity.encode()).hexdigest()
        trends.append(
            {
                "trend_id": trend_id,
                "geo": geo.upper(),
                "query": title,
                "published_at": pub_date,
                "traffic_label": traffic_label,
                "traffic_lower_bound": parse_traffic_lower_bound(traffic_label),
                "picture_url": _text(item, f"{{{HT}}}picture"),
                "picture_source": _text(item, f"{{{HT}}}picture_source"),
            }
        )

        for position, story in enumerate(item.findall(f"{{{HT}}}news_item"), start=1):
            url = _text(story, f"{{{HT}}}news_item_url")
            article_identity = f"{trend_id}|{position}|{url}"
            news_items.append(
                {
                    "news_item_id": hashlib.sha256(article_identity.encode()).hexdigest(),
                    "trend_id": trend_id,
                    "position": position,
                    "title": _text(story, f"{{{HT}}}news_item_title"),
                    "url": url,
                    "source": _text(story, f"{{{HT}}}news_item_source"),
                    "picture_url": _text(story, f"{{{HT}}}news_item_picture"),
                }
            )

    if not trends:
        raise ValueError("The RSS feed contained no trend items")
    return ParsedFeed(trends=trends, news_items=news_items)


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    geo TEXT NOT NULL,
    source_url TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    status TEXT NOT NULL,
    trend_count INTEGER NOT NULL DEFAULT 0,
    news_item_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS trends (
    trend_id TEXT PRIMARY KEY,
    geo TEXT NOT NULL,
    query TEXT NOT NULL,
    published_at TEXT NOT NULL,
    traffic_label TEXT,
    traffic_lower_bound INTEGER,
    picture_url TEXT,
    picture_source TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    latest_run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id)
);

CREATE TABLE IF NOT EXISTS run_trends (
    run_id TEXT NOT NULL REFERENCES ingestion_runs(run_id),
    trend_id TEXT NOT NULL REFERENCES trends(trend_id),
    PRIMARY KEY (run_id, trend_id)
);

CREATE TABLE IF NOT EXISTS news_items (
    news_item_id TEXT PRIMARY KEY,
    trend_id TEXT NOT NULL REFERENCES trends(trend_id),
    position INTEGER NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT,
    picture_url TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_captured_at ON ingestion_runs(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_trends_published_at ON trends(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_trend_id ON news_items(trend_id);
"""


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA)


def load_snapshot(
    connection: sqlite3.Connection,
    parsed: ParsedFeed,
    *,
    run_id: str,
    captured_at: datetime,
    geo: str,
    raw_path: Path,
    payload: bytes,
) -> None:
    captured = captured_at.isoformat()
    connection.execute(
        """
        INSERT INTO ingestion_runs (
            run_id, captured_at, geo, source_url, raw_path, payload_sha256,
            status, trend_count, news_item_count
        ) VALUES (?, ?, ?, ?, ?, ?, 'success', ?, ?)
        """,
        (
            run_id,
            captured,
            geo.upper(),
            RSS_URL.format(geo=geo.upper()),
            str(raw_path),
            hashlib.sha256(payload).hexdigest(),
            len(parsed.trends),
            len(parsed.news_items),
        ),
    )

    for trend in parsed.trends:
        connection.execute(
            """
            INSERT INTO trends (
                trend_id, geo, query, published_at, traffic_label, traffic_lower_bound,
                picture_url, picture_source, first_seen_at, last_seen_at, latest_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trend_id) DO UPDATE SET
                traffic_label = excluded.traffic_label,
                traffic_lower_bound = excluded.traffic_lower_bound,
                picture_url = excluded.picture_url,
                picture_source = excluded.picture_source,
                last_seen_at = excluded.last_seen_at,
                latest_run_id = excluded.latest_run_id
            """,
            (
                trend["trend_id"], trend["geo"], trend["query"], trend["published_at"],
                trend["traffic_label"], trend["traffic_lower_bound"], trend["picture_url"],
                trend["picture_source"], captured, captured, run_id,
            ),
        )
        connection.execute(
            "INSERT OR IGNORE INTO run_trends (run_id, trend_id) VALUES (?, ?)",
            (run_id, trend["trend_id"]),
        )

    for story in parsed.news_items:
        connection.execute(
            """
            INSERT INTO news_items (
                news_item_id, trend_id, position, title, url, source, picture_url,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(news_item_id) DO UPDATE SET
                title = excluded.title,
                source = excluded.source,
                picture_url = excluded.picture_url,
                last_seen_at = excluded.last_seen_at
            """,
            (
                story["news_item_id"], story["trend_id"], story["position"], story["title"],
                story["url"], story["source"], story["picture_url"], captured, captured,
            ),
        )


def ingest(
    *,
    geo: str = "KE",
    db_path: Path = Path("data/search_behaviour.db"),
    raw_dir: Path = Path("data/raw"),
    payload: bytes | None = None,
) -> dict[str, object]:
    captured_at = utc_now()
    payload = payload if payload is not None else fetch_rss(geo)
    raw_path = archive_payload(payload, raw_dir, geo, captured_at)
    parsed = parse_rss(payload, geo)
    run_id = hashlib.sha256(
        f"{captured_at.isoformat()}|{hashlib.sha256(payload).hexdigest()}".encode()
    ).hexdigest()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        initialize_database(connection)
        with connection:
            load_snapshot(
                connection,
                parsed,
                run_id=run_id,
                captured_at=captured_at,
                geo=geo,
                raw_path=raw_path,
                payload=payload,
            )

    return {
        "run_id": run_id,
        "captured_at": captured_at.isoformat(),
        "raw_path": str(raw_path),
        "trend_count": len(parsed.trends),
        "news_item_count": len(parsed.news_items),
        "db_path": str(db_path),
    }

