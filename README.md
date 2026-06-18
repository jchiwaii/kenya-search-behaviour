# Kenyan Search Behaviour

A discovery-first, end-to-end data project for understanding what is surging in
Google searches in Kenya. The first usable source is Google Trends' public
**Trending now RSS feed** for `KE`; it requires no API key.

## What works now

```text
Google Trends RSS (KE)
        |
        v
immutable XML snapshots -> parser/validation -> SQLite -> Streamlit dashboard
```

Each ingestion run archives the response before parsing it. The modeled layer
keeps trends and their linked news stories separate, so a later warehouse or
official API connector can reuse the same downstream shape.

## Quick start

Python 3.11+ is required.

```bash
make install
make ingest
make dashboard
```

Open the URL printed by Streamlit (normally `http://localhost:8501`). Run tests
with `make test`.

## Cloud collection with GitHub Actions

The workflow in `.github/workflows/collect-trends.yml` runs hourly without your
laptop. It collects until **1 July 2026, 00:00 Africa/Nairobi**, commits the raw
snapshot and SQLite database to the repository, then creates a final statistical
report on its next run.

To activate it:

1. Push this project to a GitHub repository.
2. In **Settings → Actions → General → Workflow permissions**, select
   **Read and write permissions** if your repository does not allow the workflow's
   declared `contents: write` permission by default.
3. Open **Actions → Collect Kenyan search trends → Run workflow** once to verify it.

Scheduled workflows run from the default branch. GitHub may occasionally delay a
scheduled run, so the final report includes an approximate hourly coverage rate.
After the report has been committed, disable or delete the schedule to avoid
unnecessary no-op workflow runs.

Without installing the package, the pipeline can also run directly:

```bash
PYTHONPATH=src python3 -m kenya_search.cli ingest
PYTHONPATH=src streamlit run dashboard/app.py
```

## Data contract

- `ingestion_runs`: one audit record per source request.
- `trends`: one row per query and published timestamp. `traffic_lower_bound` is
  parsed from Google's bucketed label such as `500+`; it is **not exact volume**.
- `news_items`: zero or more stories Google associates with each trend.
- `data/raw/...`: timestamped source responses for replay and debugging.

The dashboard defaults to the latest successful snapshot so repeated ingestion
does not inflate counts.

## Source strategy

1. **Now — public RSS:** fresh Kenyan surge signals, free and keyless. It is a
   discovery feed, not a historical measure of all popular searches.
2. **Manual research — CSV imports:** Google Trends Explore supports CSV export.
   This is the safest way to backfill interest-over-time for topics selected
   during discovery.
3. **Later — official Google Trends API:** Google's API is still limited-access
   alpha. When access is granted, add an adapter and keep the raw/model/UI layers.

An unofficial scraper is intentionally not a hard dependency. It can be added as
an experimental source, but it should not be the foundation of a scheduled
production pipeline.

## Suggested next milestone

Schedule RSS collection every 30–60 minutes for two weeks. That history will let
us measure recurring themes, trend duration, time-of-day patterns, source mix,
and genuinely Kenya-specific signals. Use those findings to decide which topics
deserve Google Trends Explore backfills and dedicated dashboard views.
