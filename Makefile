.PHONY: install ingest dashboard test

install:
	python3 -m pip install -e '.[dev]'

ingest:
	PYTHONPATH=src python3 -m kenya_search.cli ingest

dashboard:
	PYTHONPATH=src streamlit run dashboard/app.py

test:
	PYTHONPATH=src pytest -q

