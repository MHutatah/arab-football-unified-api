"""The review queue and the merge that clears it — a maintainer's only lever."""

import pytest

from arabfootball.resolve.normalize import norm
from arabfootball.resolve.resolver import Resolver
from arabfootball.resolve.review import MergeError, main, merge, queue
from arabfootball.store.db import Store


@pytest.fixture()
def store():
    database = Store(":memory:")
    yield database
    database.close()


def _canonical(store, name_en="Al Hilal", name_ar="الهلال"):
    entity = store.create_entity(type="team", name_en=name_en, name_ar=name_ar, country="SA")
    store.add_alias(entity, "365scores", "5457", name_en, "en")
    return entity


def _provisional(store, name_en="Hilal Riyadh", provider="espn", provider_id="99"):
    resolution = Resolver(store).resolve(
        type="team", provider=provider, provider_id=provider_id,
        name=name_en, country="SA")
    assert resolution.provisional
    return resolution.entity_id


def _match(store, match_id, home, away):
    store.conn.execute(
        "INSERT INTO matches (id, home_entity, away_entity, kickoff_utc, status)"
        " VALUES (?,?,?,?,'finished')",
        (match_id, home, away, "2026-03-01T18:00:00+00:00"))
    store.conn.commit()


# ── listing ─────────────────────────────────────────────────────────────────
def test_queue_lists_provisional_entities_with_aliases_and_source(store):
    _canonical(store)
    provisional = _provisional(store)

    entries = queue(store)

    assert [e["id"] for e in entries] == [provisional]
    entry = entries[0]
    assert entry["sources"] == ["espn"]
    assert ("espn", "99", "Hilal Riyadh") in [
        (a["provider"], a["provider_id"], a["name_variant"]) for a in entry["aliases"]]


def test_review_command_prints_the_queue(store, capsys, tmp_path, monkeypatch):
    db = tmp_path / "review.db"
    disk = Store(str(db))
    _canonical(disk)
    provisional = _provisional(disk)
    disk.close()

    assert main(["--db", str(db)]) == 0

    out = capsys.readouterr().out
    assert provisional in out
    assert "Hilal Riyadh" in out
    assert "espn" in out


def test_review_command_says_so_when_nothing_awaits_review(store, capsys, tmp_path):
    db = tmp_path / "empty.db"

    assert main(["--db", str(db)]) == 0
    assert "empty" in capsys.readouterr().out


# ── merging ─────────────────────────────────────────────────────────────────
def test_merge_repoints_aliases_and_deletes_the_provisional(store):
    canonical = _canonical(store)
    provisional = _provisional(store)
    _match(store, "m1", provisional, canonical)

    result = merge(store, provisional, canonical)

    assert result.canonical_id == canonical
    assert store.entity(provisional) is None
    assert queue(store) == []
    owners = {row["entity_id"] for row in store.conn.execute(
        "SELECT entity_id FROM aliases WHERE name_variant='Hilal Riyadh'")}
    assert owners == {canonical}
    # history written against the provisional id follows it to the canonical club
    assert store.conn.execute(
        "SELECT home_entity FROM matches WHERE id='m1'").fetchone()[0] == canonical


def test_merged_spelling_resolves_exactly_next_time(store):
    canonical = _canonical(store)
    provisional = _provisional(store)
    merge(store, provisional, canonical)

    # a different provider, so only the learned spelling can carry the match
    again = Resolver(store).resolve(type="team", provider="api_football",
                                    provider_id="7", name="Hilal Riyadh", country="SA")

    assert (again.entity_id, again.provisional) == (canonical, False)
    assert again.method in {"name", "fuzzy"}


def test_merge_keeps_a_name_only_provisional_spelling_as_an_alias(store):
    canonical = _canonical(store)
    provisional = store.create_entity(type="team", name_ar="الهلال السعودي",
                                      country="SA", provisional=True)

    merge(store, provisional, canonical)

    kept = store.conn.execute(
        "SELECT provider, name_variant, script FROM aliases WHERE entity_id=?"
        " AND name_variant='الهلال السعودي'", (canonical,)).fetchone()
    assert (kept["provider"], kept["script"]) == ("manual", "ar")
    assert norm("الهلال السعودي")  # the spelling is comparable, not just stored


def test_merge_is_idempotent_and_logged(store):
    canonical = _canonical(store)
    provisional = _provisional(store)

    first = merge(store, provisional, canonical)
    second = merge(store, provisional, canonical)

    assert not first.already_merged
    assert second.already_merged
    assert (second.canonical_id, second.aliases_moved) == (canonical, first.aliases_moved)
    logged = store.conn.execute("SELECT * FROM entity_merges").fetchall()
    assert len(logged) == 1
    assert (logged[0]["provisional_id"], logged[0]["canonical_id"]) == (provisional, canonical)
    assert logged[0]["merged_at"]
    assert store.conn.execute(
        "SELECT COUNT(*) FROM aliases WHERE entity_id=? AND name_variant='Hilal Riyadh'",
        (canonical,)).fetchone()[0] == 1


def test_merge_does_not_duplicate_a_spelling_both_entities_already_carry(store):
    canonical = _canonical(store)
    provisional = _provisional(store)
    # a name-only alias, the one shape the alias uniqueness constraint lets both hold
    store.add_alias(canonical, "espn", None, "Hilal Riyadh", "en")
    store.add_alias(provisional, "espn", None, "Hilal Riyadh", "en")

    merge(store, provisional, canonical)

    assert store.conn.execute(
        "SELECT COUNT(*) FROM aliases WHERE provider='espn' AND provider_id IS NULL"
        " AND name_variant='Hilal Riyadh'").fetchone()[0] == 1


def test_merge_follows_a_canonical_that_was_itself_merged_away(store):
    canonical = _canonical(store)
    middle = _provisional(store, name_en="Zaeem Al Asia", provider_id="98")
    provisional = _provisional(store, name_en="Hilal Riyadh")
    merge(store, middle, canonical)

    result = merge(store, provisional, middle)

    assert result.canonical_id == canonical
    assert store.entity(provisional) is None


def test_merge_refuses_a_target_that_is_not_a_correction(store):
    canonical = _canonical(store)
    provisional = _provisional(store)
    player = store.create_entity(type="player", name_en="Salem Al Dawsari", country="SA")

    with pytest.raises(MergeError, match="type mismatch"):
        merge(store, provisional, player)
    with pytest.raises(MergeError, match="unknown canonical"):
        merge(store, provisional, "team:does-not-exist")
    with pytest.raises(MergeError, match="itself"):
        merge(store, canonical, canonical)
    with pytest.raises(MergeError, match="unknown entity"):
        merge(store, "team:never-existed", canonical)
    # a refusal leaves the queue exactly as it was
    assert [e["id"] for e in queue(store)] == [provisional]


def test_merge_refuses_to_re_merge_into_a_different_entity(store):
    canonical = _canonical(store)
    other = store.create_entity(type="team", name_en="Al Nassr", country="SA")
    provisional = _provisional(store)
    merge(store, provisional, canonical)

    with pytest.raises(MergeError, match="already merged"):
        merge(store, provisional, other)


def test_merge_command_reports_the_correction(tmp_path, capsys):
    db = tmp_path / "merge.db"
    disk = Store(str(db))
    canonical = _canonical(disk)
    provisional = _provisional(disk)
    disk.close()

    assert main(["--db", str(db), "merge", provisional, canonical]) == 0
    assert "merged" in capsys.readouterr().out

    assert main(["--db", str(db), "merge", provisional, canonical]) == 0
    assert "already merged" in capsys.readouterr().out

    reopened = Store(str(db))
    assert reopened.entity(provisional) is None
    assert queue(reopened) == []
    reopened.close()


def test_merge_command_refuses_loudly(tmp_path, capsys):
    db = tmp_path / "bad.db"
    disk = Store(str(db))
    canonical = _canonical(disk)
    disk.close()

    assert main(["--db", str(db), "merge", "team:nope", canonical]) == 2
    assert "refused" in capsys.readouterr().out
