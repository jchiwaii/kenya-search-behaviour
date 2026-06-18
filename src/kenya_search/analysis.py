from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NAIROBI = ZoneInfo("Africa/Nairobi")


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_table(headers: list[str], rows: list[tuple[object, ...]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(_markdown_cell(value) for value in row) + " |" for row in rows)
    return lines


def _display_time(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(NAIROBI).strftime("%d %b %Y, %H:%M EAT")


def build_report(
    db_path: Path = Path("data/search_behaviour.db"),
    output_path: Path = Path("reports/2026-06-collection.md"),
) -> Path:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        summary = connection.execute(
            """
            SELECT COUNT(*) AS snapshots,
                   COUNT(DISTINCT substr(captured_at, 1, 13)) AS captured_hours,
                   MIN(captured_at) AS first_capture,
                   MAX(captured_at) AS last_capture,
                   SUM(trend_count) AS trend_observations,
                   SUM(news_item_count) AS news_observations
            FROM ingestion_runs
            WHERE status = 'success'
            """
        ).fetchone()
        if not summary or not summary["snapshots"]:
            raise ValueError("No successful ingestion runs are available to analyze")

        distinct_queries = connection.execute(
            "SELECT COUNT(DISTINCT lower(query)) FROM trends"
        ).fetchone()[0]
        distinct_stories = connection.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]

        recurring = connection.execute(
            """
            SELECT MIN(t.query) AS query,
                   COUNT(DISTINCT rt.run_id) AS snapshots,
                   COUNT(DISTINCT t.trend_id) AS episodes,
                   MAX(COALESCE(t.traffic_lower_bound, 0)) AS peak_lower_bound,
                   MIN(t.first_seen_at) AS first_seen,
                   MAX(t.last_seen_at) AS last_seen
            FROM trends t
            JOIN run_trends rt ON rt.trend_id = t.trend_id
            GROUP BY lower(t.query)
            ORDER BY snapshots DESC, peak_lower_bound DESC, query
            LIMIT 20
            """
        ).fetchall()

        sources = connection.execute(
            """
            SELECT COALESCE(NULLIF(source, ''), 'Unknown') AS source, COUNT(*) AS stories
            FROM news_items
            GROUP BY COALESCE(NULLIF(source, ''), 'Unknown')
            ORDER BY stories DESC, source
            LIMIT 15
            """
        ).fetchall()

        daily = connection.execute(
            """
            SELECT substr(first_seen_at, 1, 10) AS day, COUNT(*) AS new_trends
            FROM trends
            GROUP BY substr(first_seen_at, 1, 10)
            ORDER BY day
            """
        ).fetchall()

    first = datetime.fromisoformat(summary["first_capture"])
    last = datetime.fromisoformat(summary["last_capture"])
    expected = max(1, int((last - first).total_seconds() // 3600) + 1)
    coverage = summary["captured_hours"] / expected * 100

    recurring_rows = [
        (
            row["query"],
            row["snapshots"],
            row["episodes"],
            f"{row['peak_lower_bound']:,}+" if row["peak_lower_bound"] else "Unknown",
            _display_time(row["first_seen"]),
            _display_time(row["last_seen"]),
        )
        for row in recurring
    ]
    source_rows = [(row["source"], row["stories"]) for row in sources]
    daily_rows = [(row["day"], row["new_trends"]) for row in daily]

    lines = [
        "# Kenyan Search Behaviour — Collection Report",
        "",
        "## Collection health",
        "",
        f"- Window: {_display_time(summary['first_capture'])} to {_display_time(summary['last_capture'])}",
        f"- Successful snapshots: {summary['snapshots']:,}",
        f"- Approximate hourly coverage: {coverage:.1f}% ({summary['captured_hours']:,}/{expected:,} hours)",
        f"- Trend observations: {summary['trend_observations']:,}",
        f"- Distinct normalized queries: {distinct_queries:,}",
        f"- Linked story observations: {summary['news_observations']:,}",
        f"- Distinct linked stories: {distinct_stories:,}",
        "",
        "## Most persistent queries",
        "",
        "Persistence counts how many snapshots contained a query. Episodes count distinct published trend events.",
        "",
        *_markdown_table(
            ["Query", "Snapshots", "Episodes", "Peak bucket", "First seen", "Last seen"],
            recurring_rows,
        ),
        "",
        "## Leading linked-news sources",
        "",
        *_markdown_table(["Source", "Distinct stories"], source_rows),
        "",
        "## New trend events by ingestion day (UTC)",
        "",
        *_markdown_table(["Day", "New trend events"], daily_rows),
        "",
        "## Interpretation guardrails",
        "",
        "- Trending Now measures unusual recent surges, not the most searched terms overall.",
        "- Traffic values such as `500+` are bucket lower bounds, not exact search counts.",
        "- The feed is sampled and normalized; low-volume searches may appear as zero or be absent.",
        "- Missing scheduled runs reduce persistence estimates, so consult collection coverage first.",
        "- Theme and causality judgments require qualitative review of queries and linked reporting.",
        "",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
