"""The published file behaves like the database it was cut from.

`test_snapshot.py` checks the *properties* of the export — it is stamped, it is
vacuumed, no provider key survives. This file checks the *round trip*: that what
arrives is what was there, and that a stranger's process can answer from it.

Two halves, because "round trip" means both:

**The rows.** Every published table is compared against the working store row for
row — not against the snapshot's own stamp, which would stay self-consistent even
if the copy silently dropped half the archive. The expected side is derived from
the source with the documented redaction (`aliases.provider_id`,
`matches.provider_ids`) and the documented exclusion (`tier='reference'`,
`source_runs`, `entity_merges`) applied here, independently of the SQL that does
it in `snapshot.py`. A table that is neither exported nor declared internal is an
error in itself: the export refuses to run rather than ship an unclassified one.

**The answers.** Sprint acceptance criterion 9 — "a fresh process opens it and
answers 3, 4, 8 identically". A separate interpreter opens the exported file and
runs the *same* `answer()` this module runs against the working store: cross-script
identity, namesakes kept apart, form and head-to-head derived from the archive.
Any difference is the file, not the question. That process may not touch the
network, and a second one reads the file with stdlib ``sqlite3`` and nothing else.

The one answer the snapshot deliberately cannot give is a lookup by a provider's
own id — those keys are redacted on the way out. It is asserted here rather than
left to be discovered.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from arabfootball.derive.careers import squad
from arabfootball.derive.form import form
from arabfootball.derive.h2h import h2h
from arabfootball.resolve.normalize import norm
from arabfootball.resolve.resolver import Resolver
from arabfootball.store import snapshot as snapshot_module
from arabfootball.store.db import Store
from arabfootball.store.snapshot import (
    INTERNAL_TABLES,
    PUBLISHED_TABLES,
    export,
    read_meta,
    unclassified_tables,
)

ROOT = Path(__file__).resolve().parent.parent

PERIOD = "2026-09"
SEASON = "2025/2026"

COMPETITION = "competition:spl"
HILAL = "team:hilal"
HILAL_SD = "team:hilal-sd"
AHLI_SA = "team:ahli-sa"
AHLI_JO = "team:ahli-jo"
NASSR = "team:nassr"
PLAYER = "player:salem"

# 365Scores' own id for Al Hilal — the one the sprint criterion names.
HILAL_365_ID = "5457"

# Criterion 3 (one entity per club, whatever the spelling) and criterion 4
# (namesakes in different countries are different clubs) as one question set.
LOOKUPS = (
    ("hilal-arabic", "الهلال", "SA"),
    ("hilal-latin", "Al Hilal", "SA"),
    ("hilal-hyphenated", "Al-Hilal", "SA"),
    ("hilal-suffixed", "AlHilal SFC", "SA"),
    ("hilal-sudanese", "الهلال", "SD"),
    ("ahli-saudi", "Al Ahli", "SA"),
    ("ahli-jordanian", "Al Ahli", "JO"),
)

EXPECTED_IDS = {
    "hilal-arabic": HILAL, "hilal-latin": HILAL, "hilal-hyphenated": HILAL,
    "hilal-suffixed": HILAL, "hilal-sudanese": HILAL_SD,
    "ahli-saudi": AHLI_SA, "ahli-jordanian": AHLI_JO,
}


def answer(store) -> dict:
    """The sprint's answers 3, 4 and 8, asked of one store.

    Takes a store rather than a path because both the working database and the
    published snapshot have to answer it — the fresh-process test runs this very
    function against the file it "downloaded", so the questions cannot drift
    between the two sides of the comparison.
    """
    resolver = Resolver(store)
    resolutions = {
        label: [r.entity_id, r.method]
        for label, name, country in LOOKUPS
        for r in [resolver.resolve(type="team", provider="reader", name=name, country=country)]
    }

    recent = form(store, HILAL, 5)
    meetings = h2h(store, HILAL, NASSR)
    # The redacted column is the one documented difference between the two
    # databases; dropping it here keeps every other field under exact comparison.
    recent["matches"] = _without_provider_ids(recent["matches"])
    meetings["meetings"] = _without_provider_ids(meetings["meetings"])

    return {
        "resolutions": resolutions,
        "form": recent,
        "h2h": meetings,
        "squad": squad(store, HILAL, SEASON),
    }


def _without_provider_ids(match_rows: list[dict]) -> list[dict]:
    return [{k: v for k, v in row.items() if k != "provider_ids"} for row in match_rows]


# A separate interpreter, given only the exported file. The import of the test
# module is what guarantees it asks exactly the questions the working store was
# asked; the network guard goes up before any of them are answered.
FRESH_PROCESS = """
import json, socket, sys

from arabfootball.store.db import Store
from tests.test_snapshot_roundtrip import answer


def _no_network(*_a, **_k):
    raise AssertionError("answering from a snapshot must not touch the network")


socket.socket = _no_network
socket.create_connection = _no_network

store = Store(sys.argv[1])
print(json.dumps(answer(store), ensure_ascii=False, sort_keys=True))
"""

# The consumer promise in one program: stdlib `sqlite3`, no package, no extension.
STDLIB_ONLY = """
import json, sqlite3, sys

conn = sqlite3.connect(sys.argv[1])
conn.row_factory = sqlite3.Row
meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM snapshot_meta")}
spellings = [r[0] for r in conn.execute(
    "SELECT DISTINCT name_variant FROM aliases WHERE entity_id=? ORDER BY name_variant",
    (sys.argv[2],))]
finished = [dict(r) for r in conn.execute(
    "SELECT id, home_entity, away_entity, home_score, away_score FROM matches"
    " WHERE status='finished' AND ? IN (home_entity, away_entity) ORDER BY kickoff_utc",
    (sys.argv[2],))]
print(json.dumps({"license": meta["license"], "counts": json.loads(meta["counts"]),
                  "spellings": spellings, "finished": finished},
                 ensure_ascii=False, sort_keys=True))
"""


def _entity(store, entity_id, type, name_en, name_ar, country, *, provisional=0):
    store.conn.execute(
        "INSERT INTO entities (id,type,name_en,name_ar,country,provisional,created_at)"
        " VALUES (?,?,?,?,?,?,'2026-01-01T00:00:00+00:00')",
        (entity_id, type, name_en, name_ar, country, provisional))


def _match(store, match_id, home, away, kickoff, status, home_score, away_score, provider_id):
    store.conn.execute(
        "INSERT INTO matches (id,competition_id,season,round,home_entity,away_entity,"
        "kickoff_utc,status,home_score,away_score,provider_ids,last_synced)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,'2026-01-02T00:00:00+00:00')",
        (match_id, COMPETITION, SEASON, match_id.split(":")[1], home, away, kickoff, status,
         home_score, away_score,
         json.dumps({"365scores": provider_id}) if provider_id else None))


@pytest.fixture()
def work_db(tmp_path):
    """A working store big enough for the answers to be worth comparing.

    Two pairs of namesakes, four spellings of one club, a season of results, and
    every kind of row the export has to decide about.
    """
    store = Store(str(tmp_path / "arabfootball.db"))
    _entity(store, COMPETITION, "competition", "Saudi Pro League", "دوري روشن السعودي", "SA")
    _entity(store, HILAL, "team", "Al Hilal", "الهلال", "SA")
    _entity(store, HILAL_SD, "team", "Al Hilal", "الهلال", "SD")
    _entity(store, AHLI_SA, "team", "Al Ahli", "الأهلي", "SA")
    _entity(store, AHLI_JO, "team", "Al Ahli", "الأهلي", "JO")
    _entity(store, NASSR, "team", "Al Nassr", "النصر", "SA")
    _entity(store, PLAYER, "player", "Salem Al Dawsari", "سالم الدوسري", "SA", provisional=1)

    store.conn.executemany(
        "INSERT INTO aliases (entity_id,provider,provider_id,name_variant,script)"
        " VALUES (?,?,?,?,?)",
        [(HILAL, "365scores", HILAL_365_ID, "Al Hilal", "en"),
         (HILAL, "365scores", HILAL_365_ID, "الهلال", "ar"),
         (HILAL, "espn", "h-9", "Al-Hilal", "en"),
         (HILAL, "manual", None, "AlHilal SFC", "en"),
         # A second provider id for a spelling already carried: one published row.
         (HILAL, "365scores", "7001", "Al Hilal", "en"),
         # The Sudanese namesake spells itself identically. Different club.
         (HILAL_SD, "365scores", "9001", "Al Hilal", "en"),
         (HILAL_SD, "365scores", "9001", "الهلال", "ar"),
         (AHLI_SA, "365scores", "600", "Al Ahli", "en"),
         (AHLI_JO, "365scores", "700", "Al Ahli", "en"),
         (NASSR, "365scores", "5458", "Al Nassr", "en")])

    _match(store, "match:1", HILAL, NASSR, "2025-08-28T18:00:00+00:00", "finished", 2, 1, "g-1")
    _match(store, "match:2", NASSR, HILAL, "2025-09-14T17:00:00+00:00", "finished", 1, 1, "g-2")
    _match(store, "match:3", HILAL, NASSR, "2025-10-05T16:00:00+00:00", "finished", 0, 2, None)
    _match(store, "match:4", HILAL, AHLI_SA, "2025-11-01T16:00:00+00:00", "finished", 3, 0, "g-4")
    _match(store, "match:5", NASSR, HILAL, "2026-01-10T16:00:00+00:00", "scheduled", None, None,
           None)

    store.conn.executemany(
        "INSERT INTO appearances (player_entity,match_id,team_entity,started,minutes,goals)"
        " VALUES (?,?,?,1,90,?)",
        [(PLAYER, "match:1", HILAL, 1), (PLAYER, "match:2", HILAL, 0),
         (PLAYER, "match:4", HILAL, 2)])
    store.conn.execute(
        "INSERT INTO team_seasons (team_entity,competition_id,season,played,wins,draws,losses,"
        "points) VALUES (?,?,?,4,2,1,1,7)", (HILAL, COMPETITION, SEASON))
    store.conn.execute(
        "INSERT INTO honours (entity_id,competition_id,season,result)"
        " VALUES (?,?,'2024/2025','winner')", (HILAL, COMPETITION))
    store.conn.execute(
        "INSERT INTO facts (id,kind,subject_entity,text_en,source,published_at)"
        " VALUES ('fact:1','injury',?,'Out for three weeks','spa','2025-09-01')", (PLAYER,))
    store.conn.executemany(
        "INSERT INTO transfers (id,player_entity,from_entity,to_entity,date,type,source,tier)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [("transfer:pub", PLAYER, NASSR, HILAL, "2024-07-01", "permanent",
          "global-transfers-cc0", "publishable"),
         ("transfer:ref", PLAYER, HILAL, NASSR, "2019-07-01", "loan",
          "saudi-transfers-unstated", "reference")])

    store.conn.execute(
        "INSERT INTO source_runs (id,collector,started_at,status,errors)"
        " VALUES ('run:1','365scores','2026-09-01T00:00:00+00:00','failed',?)",
        (json.dumps([{"message": f"401 for key {HILAL_365_ID}"}]),))
    store.conn.execute(
        "INSERT INTO entity_merges (provisional_id,canonical_id,name_en,aliases_moved,merged_at)"
        " VALUES ('team:dupe',?,'Al-Hilal SFC',2,'2026-09-02T00:00:00+00:00')", (HILAL,))
    store.conn.commit()
    yield store
    store.close()


@pytest.fixture()
def source(work_db, tmp_path):
    return tmp_path / "arabfootball.db"


@pytest.fixture()
def snapshot(source, tmp_path):
    return export(source, tmp_path / "dist", period=PERIOD)


def rows(path, sql, *args):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(sql, args)]
    finally:
        conn.close()


def table(path, name):
    """Every row of a table, ordered so two databases can be compared."""
    return sorted(rows(path, f"SELECT * FROM {name}"), key=_sort_key)


def _sort_key(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False, default=str)


def count(path, table_name, where="1=1", *args):
    return rows(path, f"SELECT COUNT(*) AS n FROM {table_name} WHERE {where}", *args)[0]["n"]


def fresh_process(program, *args, cwd):
    result = subprocess.run([sys.executable, "-c", program, *args],
                            cwd=cwd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


# ── the rows: what was there is what arrives ────────────────────────────────
# Tables the export copies whole. Nothing in them is redacted, so "round trip"
# means byte-for-byte the same rows.
UNREDACTED = ("entities", "appearances", "team_seasons", "honours", "facts")


def test_tables_with_nothing_to_redact_arrive_row_for_row(source, snapshot):
    for name in UNREDACTED:
        expected = table(source, name)
        assert expected, f"{name} is empty in the fixture; the comparison would prove nothing"
        assert table(snapshot, name) == expected, name


def test_aliases_arrive_with_provider_ids_dropped_and_no_spelling_lost(source, snapshot):
    """Every (entity, provider, spelling) survives; only the id is gone."""
    expected = sorted({(r["entity_id"], r["provider"], None, r["name_variant"], r["script"])
                       for r in rows(source, "SELECT * FROM aliases")})
    published = sorted((r["entity_id"], r["provider"], r["provider_id"],
                        r["name_variant"], r["script"])
                       for r in rows(snapshot, "SELECT * FROM aliases"))
    assert published == expected
    # The collapse is only meaningful if the fixture contains a collision.
    assert len(expected) < count(source, "aliases")
    # ...and the two namesakes keep their identical spelling, one row each.
    assert count(snapshot, "aliases", "name_variant='Al Hilal'") == 2


def test_matches_arrive_with_provider_ids_dropped_and_no_result_lost(source, snapshot):
    expected = sorted(({**row, "provider_ids": None} for row in table(source, "matches")),
                      key=_sort_key)
    assert table(snapshot, "matches") == expected
    assert any(row["provider_ids"] for row in table(source, "matches")), "nothing to redact"


def test_transfers_arrive_minus_the_reference_tier(source, snapshot):
    expected = [row for row in table(source, "transfers") if row["tier"] == "publishable"]
    assert table(snapshot, "transfers") == expected
    assert count(source, "transfers", "tier='reference'") == 1, "nothing to exclude"


def test_internal_tables_arrive_not_at_all(source, snapshot):
    for name in INTERNAL_TABLES:
        assert count(source, name) > 0, f"{name} is empty in the fixture"
        assert count(snapshot, name) == 0, name


def test_the_stamped_counts_are_the_source_rows_that_were_publishable(source, snapshot):
    """The stamp is checked against the store, not against the file it describes."""
    distinct_aliases = len({(r["entity_id"], r["provider"], r["name_variant"], r["script"])
                            for r in rows(source, "SELECT * FROM aliases")})
    assert read_meta(snapshot)["counts"] == {
        "entities": count(source, "entities"),
        "aliases": distinct_aliases,
        "matches": count(source, "matches"),
        "appearances": count(source, "appearances"),
        "team_seasons": count(source, "team_seasons"),
        "transfers": count(source, "transfers", "tier='publishable'"),
        "honours": count(source, "honours"),
        "facts": count(source, "facts"),
    }


# ── the rows: nothing falls between the two lists ───────────────────────────
def test_every_schema_table_is_either_published_or_declared_internal():
    """Exclusion is omission, so an unlisted table would ship nothing, quietly."""
    assert unclassified_tables() == ()


def test_a_table_nobody_classified_stops_the_export(source, tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot_module, "PUBLISHED_TABLES",
                        tuple(t for t in PUBLISHED_TABLES if t != "facts"))
    with pytest.raises(RuntimeError, match="facts"):
        export(source, tmp_path / "dist", period=PERIOD)
    assert not (tmp_path / "dist").exists(), "a refused export must leave no half-file"


# ── the answers: a fresh process, a downloaded file ─────────────────────────
def test_a_fresh_process_answers_identity_form_and_h2h_identically(work_db, snapshot):
    """Sprint criterion 9: the published file answers 3, 4 and 8 as the store does."""
    published = fresh_process(FRESH_PROCESS, str(snapshot), cwd=ROOT)
    assert published == json.loads(json.dumps(answer(work_db), ensure_ascii=False))

    # Stated outright, so the comparison cannot pass by being equally wrong.
    assert {label: entity for label, (entity, _) in published["resolutions"].items()} \
        == EXPECTED_IDS
    assert [method for _, method in published["resolutions"].values()] == ["name"] * len(LOOKUPS)
    assert published["form"]["played"] == 4
    assert (published["form"]["wins"], published["form"]["draws"],
            published["form"]["losses"]) == (2, 1, 1)
    assert published["h2h"]["summary"] == {"wins": 1, "draws": 1, "losses": 1}
    assert published["squad"] == [{"player": PLAYER, "name_ar": "سالم الدوسري",
                                   "name_en": "Salem Al Dawsari", "appearances": 3}]


def test_a_fresh_process_reads_the_snapshot_with_stdlib_sqlite3_alone(source, snapshot, tmp_path):
    """No package, no extension, no working directory: `import sqlite3` and a path."""
    read = fresh_process(STDLIB_ONLY, str(snapshot), HILAL, cwd=tmp_path)

    assert read["license"] == "ODbL-1.0"
    assert read["counts"] == read_meta(snapshot)["counts"]
    assert read["spellings"] == sorted(
        {r["name_variant"] for r in rows(source, "SELECT * FROM aliases WHERE entity_id=?", HILAL)})
    assert read["finished"] == rows(
        source,
        "SELECT id, home_entity, away_entity, home_score, away_score FROM matches"
        " WHERE status='finished' AND ? IN (home_entity, away_entity) ORDER BY kickoff_utc",
        HILAL)


def test_the_one_answer_a_snapshot_cannot_give_is_a_provider_id_lookup(work_db, snapshot):
    """Resolution by provider key is producer-side, by design: the keys are redacted.

    The names carry that lookup instead, which is why every spelling ships — a
    consumer resolves `5457`'s club by asking for "Al Hilal" in SA.
    """
    assert work_db.find_by_provider("365scores", HILAL_365_ID) == HILAL

    published = Store(str(snapshot))
    try:
        assert published.find_by_provider("365scores", HILAL_365_ID) is None
        assert published.find_by_norm("team", "SA", norm("Al Hilal")) == [HILAL]
    finally:
        published.close()
