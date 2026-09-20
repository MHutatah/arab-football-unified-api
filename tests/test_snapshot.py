"""The published snapshot: stamped, compact, and safe to redistribute.

What ships is not the working database. It has to tell a practitioner what it is
(version, date, licence, coverage, counts), it has to leave every provider key and
every internal-only row behind, and it has to be small enough to download.
"""
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from arabfootball.resolve.resolver import Resolver
from arabfootball.store.db import Store
from arabfootball.store.snapshot import export, main, read_meta

ROOT = Path(__file__).resolve().parent.parent

PERIOD = "2026-09"
GENERATED_AT = "2026-09-20T09:00:00+00:00"

COMPETITION = "competition:spl"
HILAL = "team:hilal"
NASSR = "team:nassr"
PLAYER = "player:salem"

# A provider key distinctive enough to grep the exported bytes for.
PROVIDER_KEY = "365k-5457-secret"


def _entity(store, entity_id, type, name_en, name_ar, *, country="SA", provisional=0):
    store.conn.execute(
        "INSERT INTO entities (id,type,name_en,name_ar,country,provisional,created_at)"
        " VALUES (?,?,?,?,?,?,'2026-01-01T00:00:00+00:00')",
        (entity_id, type, name_en, name_ar, country, provisional))


@pytest.fixture()
def work_db(tmp_path):
    """A working store with everything the export has to think about."""
    path = tmp_path / "arabfootball.db"
    store = Store(str(path))
    _entity(store, COMPETITION, "competition", "Saudi Pro League", "دوري روشن السعودي")
    _entity(store, HILAL, "team", "Al Hilal", "الهلال")
    _entity(store, NASSR, "team", "Al Nassr", "النصر")
    # Lineup-created identities are provisional until a maintainer reviews them.
    _entity(store, PLAYER, "player", "Salem Al Dawsari", "سالم الدوسري", provisional=1)

    store.conn.executemany(
        "INSERT INTO aliases (entity_id,provider,provider_id,name_variant,script)"
        " VALUES (?,?,?,?,?)",
        [(HILAL, "365scores", PROVIDER_KEY, "Al Hilal", "en"),
         (HILAL, "365scores", PROVIDER_KEY, "الهلال", "ar"),
         # Same spelling, a second provider id: one published row, not two.
         (HILAL, "365scores", "5457", "Al Hilal", "en"),
         (NASSR, "365scores", "5458", "Al Nassr", "en")])

    store.conn.execute(
        "INSERT INTO matches (id,competition_id,season,round,home_entity,away_entity,"
        "kickoff_utc,status,home_score,away_score,provider_ids,last_synced)"
        " VALUES ('match:1',?,'2025/2026','1',?,?,'2025-08-28T18:00:00+00:00','finished',"
        "2,1,?,'2025-08-28T20:00:00+00:00')",
        (COMPETITION, HILAL, NASSR, json.dumps({"365scores": PROVIDER_KEY})))
    store.conn.execute(
        "INSERT INTO matches (id,competition_id,season,round,home_entity,away_entity,"
        "kickoff_utc,status,provider_ids,last_synced)"
        " VALUES ('match:2',?,'2025/2026','2',?,?,'2025-09-14T17:00:00+00:00','scheduled',"
        "NULL,NULL)",
        (COMPETITION, NASSR, HILAL))
    store.conn.execute(
        "INSERT INTO appearances (player_entity,match_id,team_entity,started,minutes,goals)"
        " VALUES (?, 'match:1', ?, 1, 90, 1)", (PLAYER, HILAL))
    store.conn.execute(
        "INSERT INTO team_seasons (team_entity,competition_id,season,played,wins,points)"
        " VALUES (?,?,'2025/2026',1,1,3)", (HILAL, COMPETITION))
    store.conn.execute(
        "INSERT INTO honours (entity_id,competition_id,season,result)"
        " VALUES (?,?,'2024/2025','winner')", (HILAL, COMPETITION))
    store.conn.execute(
        "INSERT INTO facts (id,kind,subject_entity,text_en,source,published_at)"
        " VALUES ('fact:1','injury',?,'Out for three weeks','spa','2025-09-01')", (PLAYER,))

    # One redistributable transfer and one from an unstated-licence source.
    store.conn.executemany(
        "INSERT INTO transfers (id,player_entity,from_entity,to_entity,date,type,source,tier)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [("transfer:pub", PLAYER, NASSR, HILAL, "2024-07-01", "permanent",
          "global-transfers-cc0", "publishable"),
         ("transfer:ref", PLAYER, HILAL, NASSR, "2019-07-01", "loan",
          "saudi-transfers-unstated", "reference")])

    # Producer-side bookkeeping.
    store.conn.execute(
        "INSERT INTO source_runs (id,collector,started_at,finished_at,status,errors)"
        " VALUES ('run:1','365scores','2026-09-01T00:00:00+00:00',"
        "'2026-09-01T00:00:10+00:00','failed',?)",
        (json.dumps([{"type": "HTTPError", "message": f"401 for key {PROVIDER_KEY}"}]),))
    store.conn.execute(
        "INSERT INTO entity_merges (provisional_id,canonical_id,name_en,aliases_moved,merged_at)"
        " VALUES ('team:dupe',?,'Al-Hilal SFC',2,'2026-09-02T00:00:00+00:00')", (HILAL,))
    store.conn.commit()
    yield store
    store.close()


@pytest.fixture()
def snapshot(work_db, tmp_path):
    return export(tmp_path / "arabfootball.db", tmp_path / "dist",
                  period=PERIOD, generated_at=GENERATED_AT)


def rows(path, sql, *args):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, args)]
    finally:
        conn.close()


def count(path, table):
    return rows(path, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"]


# ── the file ────────────────────────────────────────────────────────────────
def test_export_writes_dated_file_into_the_output_directory(snapshot, tmp_path):
    assert snapshot == tmp_path / "dist" / f"arabfootball-{PERIOD}.db"
    assert snapshot.is_file()


def test_period_defaults_to_the_current_utc_month(work_db, tmp_path):
    path = export(tmp_path / "arabfootball.db", tmp_path / "dist")
    assert path.name == f"arabfootball-{datetime.now(UTC):%Y-%m}.db"


def test_rejects_a_period_that_is_not_a_month(work_db, tmp_path):
    with pytest.raises(ValueError, match="YYYY-MM"):
        export(tmp_path / "arabfootball.db", tmp_path / "dist", period="2026-13")


def test_missing_store_is_refused_rather_than_created(tmp_path):
    with pytest.raises(FileNotFoundError):
        export(tmp_path / "nothing.db", tmp_path / "dist", period=PERIOD)
    assert not (tmp_path / "dist" / f"arabfootball-{PERIOD}.db").exists()


def test_reexporting_a_period_rebuilds_it_rather_than_accumulating(work_db, tmp_path):
    first = export(tmp_path / "arabfootball.db", tmp_path / "dist", period=PERIOD)
    before = read_meta(first)["counts"]
    second = export(tmp_path / "arabfootball.db", tmp_path / "dist", period=PERIOD)
    assert second == first
    assert read_meta(second)["counts"] == before


# ── the stamp ───────────────────────────────────────────────────────────────
def test_stamp_carries_version_date_and_licence(snapshot):
    meta = read_meta(snapshot)
    assert meta["version"].endswith(f"+{PERIOD}")
    assert meta["generated_at"] == GENERATED_AT
    assert meta["license"] == "ODbL-1.0"
    assert meta["license_url"].startswith("https://opendatacommons.org/licenses/odbl/")
    assert "arab-football-unified-api" in meta["attribution"]


def test_version_can_be_pinned_by_the_publisher(work_db, tmp_path):
    path = export(tmp_path / "arabfootball.db", tmp_path / "dist",
                  period=PERIOD, version="2026.09.1")
    assert read_meta(path)["version"] == "2026.09.1"


def test_coverage_says_what_the_snapshot_is_about(snapshot):
    coverage = read_meta(snapshot)["coverage"]
    assert coverage["countries"] == ["SA"]
    assert coverage["seasons"] == ["2025/2026"]
    assert coverage["matches_from"] == "2025-08-28"
    assert coverage["matches_to"] == "2025-09-14"
    assert coverage["competitions"] == [
        {"id": COMPETITION, "name_ar": "دوري روشن السعودي",
         "name_en": "Saudi Pro League", "seasons": ["2025/2026"]}]
    # Unreviewed identities ship, but the consumer is told how many there are.
    assert coverage["provisional_entities"] == 1


def test_counts_describe_the_exported_file_not_the_working_store(snapshot):
    counts = read_meta(snapshot)["counts"]
    for table, expected in counts.items():
        assert count(snapshot, table) == expected, table
    assert counts["matches"] == 2
    assert counts["entities"] == 4
    # The reference-tier transfer is counted nowhere, because it is not here.
    assert counts["transfers"] == 1


def test_stamp_is_readable_with_stdlib_sqlite3_alone(snapshot):
    stamped = {row["key"]: row["value"] for row in rows(snapshot, "SELECT * FROM snapshot_meta")}
    assert {"version", "generated_at", "license", "coverage", "counts"} <= set(stamped)
    assert json.loads(stamped["counts"])["appearances"] == 1


# ── redaction ───────────────────────────────────────────────────────────────
def test_no_provider_key_survives_the_export(snapshot):
    assert all(row["provider_id"] is None for row in rows(snapshot, "SELECT * FROM aliases"))
    assert all(row["provider_ids"] is None for row in rows(snapshot, "SELECT * FROM matches"))
    # Belt and braces: the key is not anywhere in the published bytes either.
    assert PROVIDER_KEY.encode() not in snapshot.read_bytes()


def test_spellings_survive_so_the_snapshot_still_resolves_names(snapshot):
    """Provider ids are the producer's business; the name variants are the product."""
    published = Store(str(snapshot))
    try:
        resolution = Resolver(published).resolve(
            type="team", provider="reader", name="الهلال", country="SA")
        assert resolution.entity_id == HILAL
        assert resolution.method == "name"
    finally:
        published.close()


def test_aliases_that_differed_only_by_provider_id_collapse_to_one_row(snapshot):
    variants = rows(
        snapshot,
        "SELECT name_variant FROM aliases WHERE entity_id=? AND name_variant='Al Hilal'",
        HILAL)
    assert len(variants) == 1


# ── exclusion ───────────────────────────────────────────────────────────────
def test_internal_only_rows_are_left_behind(work_db, snapshot):
    assert count(snapshot, "source_runs") == 0
    assert count(snapshot, "entity_merges") == 0
    # ...and they are still in the working database, which is where they belong.
    assert work_db.conn.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0] == 1
    assert work_db.conn.execute("SELECT COUNT(*) FROM entity_merges").fetchone()[0] == 1


def test_reference_tier_transfers_are_never_published(work_db, snapshot):
    assert [row["id"] for row in rows(snapshot, "SELECT id FROM transfers")] == ["transfer:pub"]
    assert work_db.conn.execute(
        "SELECT COUNT(*) FROM transfers WHERE tier='reference'").fetchone()[0] == 1


def test_the_archive_itself_is_published_in_full(snapshot):
    assert count(snapshot, "matches") == 2
    assert count(snapshot, "appearances") == 1
    assert count(snapshot, "team_seasons") == 1
    assert count(snapshot, "honours") == 1
    assert count(snapshot, "facts") == 1
    # Provisional identities carry the appearance spine; dropping them would
    # drop the careers and squads derived from it.
    assert len(rows(snapshot, "SELECT id FROM entities WHERE provisional=1")) == 1


# ── compactness ─────────────────────────────────────────────────────────────
def test_snapshot_is_vacuumed(work_db, tmp_path):
    """Free pages left by deletes in the working store never reach a download."""
    source = tmp_path / "arabfootball.db"
    work_db.conn.executemany(
        "INSERT INTO facts (id,kind,text_en) VALUES (?,'news',?)",
        [(f"fact:bulk:{i}", "x" * 2000) for i in range(500)])
    work_db.conn.commit()
    work_db.conn.execute("DELETE FROM facts WHERE id LIKE 'fact:bulk:%'")
    work_db.conn.commit()

    path = export(source, tmp_path / "dist", period=PERIOD)
    assert rows(path, "PRAGMA freelist_count")[0]["freelist_count"] == 0
    assert path.stat().st_size < source.stat().st_size


# ── the command ─────────────────────────────────────────────────────────────
def test_cli_writes_the_snapshot_and_reports_it(work_db, tmp_path, capsys):
    assert main(["--db", str(tmp_path / "arabfootball.db"),
                 "--out", str(tmp_path / "dist"), "--period", PERIOD]) == 0
    out = capsys.readouterr().out
    assert f"arabfootball-{PERIOD}.db" in out
    assert "license=ODbL-1.0" in out
    assert (tmp_path / "dist" / f"arabfootball-{PERIOD}.db").is_file()


def test_cli_refuses_a_missing_store(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "nothing.db"), "--out", str(tmp_path / "dist")]) == 2
    assert "refused" in capsys.readouterr().out


def test_script_entry_point_runs_standalone(work_db, tmp_path):
    """`make snapshot` shells out to the script, so the script has to work."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "make_snapshot.py"),
         "--db", str(tmp_path / "arabfootball.db"), "--out", str(tmp_path / "dist")],
        capture_output=True, text=True, cwd=ROOT, check=False)
    assert result.returncode == 0, result.stderr
    expected = tmp_path / "dist" / f"arabfootball-{datetime.now(UTC):%Y-%m}.db"
    assert expected.is_file()


def test_make_snapshot_target_writes_into_dist():
    """The acceptance criterion is the make target, not just the module."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("\nsnapshot:", 1)[1].split("\n\n", 1)[0]
    assert "scripts/make_snapshot.py" in target
    assert "--out dist/" in target
