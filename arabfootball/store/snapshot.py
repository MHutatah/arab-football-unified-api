"""Export a stamped, publishable SQLite snapshot of the store.

The working database belongs to the producer: it carries collector run logs, the
maintainer's merge audit trail, every provider's own keys, and rows from sources
we are allowed to *read* but not to redistribute. The snapshot is the product —
one compact file a stranger downloads, opens with stdlib ``sqlite3``, and cites.

Three things happen on the way out.

**Stamping.** ``snapshot_meta`` records what the file *is*: version,
``generated_at``, licence, coverage and per-table row counts. A practitioner can
then cite the exact database they used instead of "the Arab football one".

**Redaction.** A published row is keyed by our language-neutral canonical id and
nothing else, so every provider key leaves at the door: ``aliases.provider_id``
and ``matches.provider_ids`` are dropped. The provider *name* stays — attribution
has to survive into the snapshot — and so does every spelling, because the name
variants are what resolution actually runs on.

**Exclusion.** Internal-only rows never ship. ``source_runs`` (collector
diagnostics, including the error payloads of failed fetches) and
``entity_merges`` (the correction audit trail) are producer-side tables and are
not copied at all; a ``tier='reference'`` transfer is filtered out, because an
unstated-licence source may point us at a fact but may never be redistributed
through us (`docs/sources.md`). Every table in the schema has to be on one side
of that line: a table nobody has classified stops the export rather than
silently never shipping.

Unreviewed (``provisional``) entities *do* ship: they are the honest state of an
identity rather than a wrong guess, and the appearance spine that careers, squads
and head-to-head derive from hangs off them. How many there are is stamped into
``coverage``, so a consumer can weigh it instead of discovering it.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from arabfootball import __version__
from arabfootball.store.db import Store

LICENSE = "ODbL-1.0"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
ATTRIBUTION = (
    "Arab Football Unified API — https://github.com/MHutatah/arab-football-unified-api"
)

# Only rows from a source whose licence permits redistribution are exported.
PUBLISHABLE_TIER = "publishable"

PERIOD_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Producer-side tables: run observability and the merge audit trail say nothing
# to a consumer about football and everything about how we work.
INTERNAL_TABLES = ("source_runs", "entity_merges")

# Written by the export itself rather than copied from the store.
STAMP_TABLES = ("snapshot_meta",)

# What ships, in foreign-key dependency order. `SELECT *` is safe where nothing
# is redacted — both databases are built from the same `schema.sql` — while the
# redacting copies name their columns, so what gets dropped is visible here.
COPY_STATEMENTS: tuple[tuple[str, str], ...] = (
    ("entities", "INSERT INTO main.entities SELECT * FROM src.entities"),
    (
        "aliases",
        # DISTINCT because two provider ids for one spelling collapse into the
        # same row once the ids are gone.
        "INSERT INTO main.aliases (entity_id,provider,provider_id,name_variant,script)"
        " SELECT DISTINCT entity_id, provider, NULL, name_variant, script FROM src.aliases",
    ),
    (
        "matches",
        "INSERT INTO main.matches (id,competition_id,season,round,home_entity,away_entity,"
        "kickoff_utc,venue_id,status,home_score,away_score,provider_ids,last_synced)"
        " SELECT id,competition_id,season,round,home_entity,away_entity,kickoff_utc,"
        "venue_id,status,home_score,away_score,NULL,last_synced FROM src.matches",
    ),
    ("appearances", "INSERT INTO main.appearances SELECT * FROM src.appearances"),
    ("team_seasons", "INSERT INTO main.team_seasons SELECT * FROM src.team_seasons"),
    (
        "transfers",
        "INSERT INTO main.transfers SELECT * FROM src.transfers WHERE tier = ?",
    ),
    ("honours", "INSERT INTO main.honours SELECT * FROM src.honours"),
    ("facts", "INSERT INTO main.facts SELECT * FROM src.facts"),
)

PUBLISHED_TABLES = tuple(table for table, _ in COPY_STATEMENTS)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def snapshot_name(period: str) -> str:
    """The published filename for a snapshot period, e.g. ``2026-09``."""
    if not PERIOD_PATTERN.match(period):
        raise ValueError(f"snapshot period must look like YYYY-MM, got {period!r}")
    return f"arabfootball-{period}.db"


def unclassified_tables() -> tuple[str, ...]:
    """Schema tables this module neither publishes nor declares internal.

    A table added to ``schema.sql`` and to nothing else would otherwise just
    never ship — silently, because omission from :data:`COPY_STATEMENTS` is what
    exclusion looks like. Deciding is cheap; discovering a missing table in a
    published file a month later is not, so the export refuses to run until
    someone has said which side of the line the new table is on.
    """
    store = Store(":memory:")
    try:
        names = {row[0] for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    finally:
        store.close()
    return tuple(sorted(names - set(PUBLISHED_TABLES) - set(INTERNAL_TABLES) - set(STAMP_TABLES)))


def export(db_path: str | Path, out_dir: str | Path = "dist", *, period: str | None = None,
           version: str | None = None, generated_at: str | None = None) -> Path:
    """Write ``<out_dir>/arabfootball-YYYY-MM.db`` and return its path.

    Re-exporting the same period overwrites it: a month's snapshot is rebuilt
    from the store, never accumulated across runs.
    """
    source = Path(db_path)
    if not source.is_file():
        raise FileNotFoundError(f"no database at {source}")

    unclassified = unclassified_tables()
    if unclassified:
        raise RuntimeError(
            "schema tables are neither exported nor declared internal: "
            + ", ".join(unclassified)
            + " — add them to COPY_STATEMENTS or to INTERNAL_TABLES")

    generated_at = generated_at or _now()
    period = period or generated_at[:7]
    out_path = Path(out_dir) / snapshot_name(period)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)

    # The snapshot is the same schema, empty: identical indexes, identical types.
    Store(str(out_path)).close()

    conn = sqlite3.connect(out_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ATTACH DATABASE ? AS src", (str(source),))
        for table, sql in COPY_STATEMENTS:
            conn.execute(sql, (PUBLISHABLE_TIER,) if table == "transfers" else ())
        _stamp(conn, version=version or f"{__version__}+{period}", generated_at=generated_at)
        conn.commit()
        conn.execute("DETACH DATABASE src")
        # Compact last, once every row the file will ever hold is in it.
        conn.execute("VACUUM")
    finally:
        conn.close()
    return out_path


def read_meta(db_path: str | Path) -> dict:
    """The stamp on a snapshot, with ``coverage`` and ``counts`` parsed back."""
    conn = sqlite3.connect(db_path)
    try:
        meta = {row[0]: row[1] for row in conn.execute("SELECT key, value FROM snapshot_meta")}
    finally:
        conn.close()
    for key in ("coverage", "counts"):
        if meta.get(key):
            meta[key] = json.loads(meta[key])
    return meta


# ── stamping ────────────────────────────────────────────────────────────────
def _stamp(conn: sqlite3.Connection, *, version: str, generated_at: str) -> None:
    meta = {
        "version": version,
        "generated_at": generated_at,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "attribution": ATTRIBUTION,
        "coverage": json.dumps(_coverage(conn), ensure_ascii=False, sort_keys=True),
        "counts": json.dumps(_counts(conn), sort_keys=True),
    }
    conn.executemany(
        "INSERT OR REPLACE INTO main.snapshot_meta (key, value) VALUES (?,?)",
        sorted(meta.items()))


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row counts of the exported file itself, not of what it was cut from."""
    return {table: conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
            for table in PUBLISHED_TABLES}


def _coverage(conn: sqlite3.Connection) -> dict:
    """What this snapshot is *about*: countries, competitions, seasons, dates."""
    countries = [row[0] for row in conn.execute(
        "SELECT DISTINCT country FROM main.entities"
        " WHERE country IS NOT NULL AND country <> '' ORDER BY country")]

    competitions: dict[str, dict] = {}
    for row in conn.execute(
            "SELECT c.id AS id, c.name_ar AS name_ar, c.name_en AS name_en,"
            " m.season AS season FROM main.matches m"
            " JOIN main.entities c ON c.id = m.competition_id"
            " GROUP BY c.id, c.name_ar, c.name_en, m.season ORDER BY c.id, m.season"):
        competition = competitions.setdefault(row["id"], {
            "id": row["id"], "name_ar": row["name_ar"], "name_en": row["name_en"],
            "seasons": []})
        if row["season"]:
            competition["seasons"].append(row["season"])

    span = conn.execute(
        "SELECT MIN(kickoff_utc) AS first, MAX(kickoff_utc) AS last FROM main.matches").fetchone()
    seasons = [row[0] for row in conn.execute(
        "SELECT DISTINCT season FROM main.matches WHERE season IS NOT NULL ORDER BY season")]
    provisional = conn.execute(
        "SELECT COUNT(*) FROM main.entities WHERE provisional = 1").fetchone()[0]

    return {
        "countries": countries,
        "competitions": list(competitions.values()),
        "seasons": seasons,
        "matches_from": (span["first"] or "")[:10] or None,
        "matches_to": (span["last"] or "")[:10] or None,
        # Identities the resolver refused to guess at: shipped, but declared.
        "provisional_entities": provisional,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/make_snapshot.py",
        description="Export a stamped, publishable SQLite snapshot for distribution.")
    parser.add_argument("--db", default="arabfootball.db", help="path to the working store")
    parser.add_argument("--out", default="dist/", help="directory to write the snapshot into")
    parser.add_argument("--period", help="YYYY-MM the snapshot covers (default: now, UTC)")
    parser.add_argument("--version", dest="version",
                        help="version to stamp (default: <code version>+<period>)")
    args = parser.parse_args(argv)

    try:
        path = export(args.db, args.out, period=args.period, version=args.version)
    except (FileNotFoundError, ValueError) as exc:
        print(f"refused: {exc}")
        return 2

    meta = read_meta(path)
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KiB)")
    print(f"  version={meta['version']} generated_at={meta['generated_at']}"
          f" license={meta['license']}")
    print("  counts: " + ", ".join(f"{table}={count}"
                                   for table, count in sorted(meta["counts"].items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
