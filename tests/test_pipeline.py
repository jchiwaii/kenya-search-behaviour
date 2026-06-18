import sqlite3
from pathlib import Path

from kenya_search.pipeline import ingest, parse_rss, parse_traffic_lower_bound


FIXTURE = Path(__file__).parent / "fixtures" / "sample.xml"


def test_parse_traffic_lower_bound() -> None:
    assert parse_traffic_lower_bound("2,000+") == 2000
    assert parse_traffic_lower_bound("500+") == 500
    assert parse_traffic_lower_bound("") is None


def test_parse_feed() -> None:
    parsed = parse_rss(FIXTURE.read_bytes())
    assert len(parsed.trends) == 1
    assert parsed.trends[0]["query"] == "fuel prices kenya"
    assert parsed.trends[0]["traffic_lower_bound"] == 2000
    assert parsed.trends[0]["published_at"] == "2026-06-18T13:40:00+00:00"
    assert parsed.news_items[0]["source"] == "Example News"


def test_end_to_end_ingestion(tmp_path: Path) -> None:
    db_path = tmp_path / "trends.db"
    result = ingest(
        db_path=db_path,
        raw_dir=tmp_path / "raw",
        payload=FIXTURE.read_bytes(),
    )
    assert result["trend_count"] == 1
    assert Path(result["raw_path"]).exists()

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM trends").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM news_items").fetchone()[0] == 1
