"""Export a stamped SQLite snapshot for publishing.

    make snapshot                       # dist/arabfootball-YYYY-MM.db
    python scripts/make_snapshot.py --db arabfootball.db --out dist/

A thin entry point: the export itself lives in `arabfootball.store.snapshot`, so
it is importable, lintable and tested like the rest of the package.
"""
from arabfootball.store.snapshot import main

if __name__ == "__main__":
    raise SystemExit(main())
