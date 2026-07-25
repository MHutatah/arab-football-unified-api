# Kooora API — consumer targets are the first three; the rest are producer-side.
.PHONY: help install test lint pull-db serve init-db collect-saudi snapshot review

DB ?= kooora.db

help:
	@echo "Consumer:"
	@echo "  make pull-db      download the latest published snapshot (ODbL)"
	@echo "  make serve        run the read API on :8100 against $(DB)"
	@echo "  make install      install the package + dev tools"
	@echo "Producer:"
	@echo "  make init-db      create an empty DB from schema.sql"
	@echo "  make collect-saudi  ingest the current Saudi Pro League season"
	@echo "  make snapshot     export a stamped SQLite snapshot for publishing"
	@echo "  make review       list provisional entities awaiting review"
	@echo "  make test / lint"

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check kooora tests

init-db:
	python -c "from kooora.store.db import Store; Store('$(DB)').close(); print('created $(DB)')"

# Consumer entry point: fetch the latest monthly snapshot from GitHub Releases.
pull-db:
	@echo "Fetching latest snapshot -> $(DB)"
	@python scripts/pull_db.py --out $(DB)

serve:
	uvicorn kooora.api.main:app --host 0.0.0.0 --port 8100

collect-saudi:
	python -m kooora.collectors.run --competition saudi --db $(DB)

snapshot:
	python scripts/make_snapshot.py --db $(DB) --out dist/

review:
	python -m kooora.resolve.review --db $(DB)
