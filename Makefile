# Arab Football Unified API — consumer targets are the first three; the rest are producer-side.
.PHONY: help install test lint pull-db serve init-db collect-saudi snapshot review merge

DB ?= arabfootball.db
# The interpreter `make snapshot` runs. Overridable so the round-trip test can
# run the target itself under the interpreter the suite is running, rather than
# assert about the recipe's text.
PYTHON ?= python

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
	@echo "  make merge FROM=<provisional-id> INTO=<canonical-id>"
	@echo "  make test / lint"

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check arabfootball tests

init-db:
	python -c "from arabfootball.store.db import Store; Store('$(DB)').close(); print('created $(DB)')"

# Consumer entry point: fetch the latest monthly snapshot from GitHub Releases.
pull-db:
	@echo "Fetching latest snapshot -> $(DB)"
	@python scripts/pull_db.py --out $(DB)

serve:
	uvicorn arabfootball.api.main:app --host 0.0.0.0 --port 8100

collect-saudi:
	python -m arabfootball.collectors.run --competition saudi --db $(DB)

snapshot:
	$(PYTHON) scripts/make_snapshot.py --db $(DB) --out dist/

review:
	python -m arabfootball.resolve.review --db $(DB)

# One-liner correction: fold a provisional entity into the club it really is.
merge:
	python -m arabfootball.resolve.review --db $(DB) merge $(FROM) $(INTO)
