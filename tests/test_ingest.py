import json
from pathlib import Path

import httpx
import pytest

from arabfootball.collectors.ingest import ingest
from arabfootball.collectors.scores365 import Scores365Collector
from arabfootball.resolve.resolver import Resolver
from arabfootball.store.db import Store


def game(**overrides):
    """One normalized record, in the shape Scores365Collector emits."""
    record = {
        "home_team": {"name": "Al Hilal", "provider_ids": {"365scores": "5457"}},
        "away_team": {"name": "Al Riyadh", "provider_ids": {"365scores": "5458"}},
        "kickoff_utc": "2025-08-28T18:00:00+00:00",
        "status": "scheduled",
        "home_score": None,
        "away_score": None,
        "provider_ids": {"365scores": "9001"},
        "competition_provider_ids": {"365scores": "649"},
    }
    record.update(overrides)
    return record


@pytest.fixture()
def store():
    value = Store(":memory:")
    yield value
    value.close()


def seed_club(store, entity_id, name_en, name_ar, provider_id, country="SA"):
    store.conn.execute(
        "INSERT INTO entities (id,type,name_en,name_ar,country,provisional,created_at)"
        " VALUES (?,?,?,?,?,0,'2025-01-01T00:00:00+00:00')",
        (entity_id, "team", name_en, name_ar, country))
    store.conn.commit()
    store.add_alias(entity_id, "365scores", provider_id, name_en, "en")
    return entity_id


def matches(store):
    return [dict(r) for r in store.conn.execute("SELECT * FROM matches ORDER BY kickoff_utc")]


def count(store, table):
    return store.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


def test_both_clubs_resolve_to_entities_before_the_match_is_stored(store):
    hilal = seed_club(store, "team:hilal", "Al Hilal", "الهلال", "5457")

    result = ingest(store, [game()], country="SA")

    assert (result.inserted, result.updated, result.unchanged) == (1, 0, 0)
    row = store.match(result.match_ids[0])
    assert row["home_entity"] == hilal
    # The unseeded away club is resolved too — as a provisional entity, never as
    # a raw provider name dropped into the match row.
    away = store.entity(row["away_entity"])
    assert (away["type"], away["name_en"], away["provisional"]) == ("team", "Al Riyadh", 1)
    assert store.find_by_provider("365scores", "5458") == away["id"]
    assert row["last_synced"] is not None


def test_a_known_competition_id_attaches_the_match_without_inventing_one(store):
    store.conn.execute(
        "INSERT INTO entities (id,type,name_en,country,provisional,created_at)"
        " VALUES ('comp:spl','competition','Saudi Pro League','SA',0,"
        "'2025-01-01T00:00:00+00:00')")
    store.conn.commit()
    store.add_alias("comp:spl", "365scores", "649", "Saudi Pro League", "en")

    known = ingest(store, [game()], country="SA")
    assert store.match(known.match_ids[0])["competition_id"] == "comp:spl"

    # An id we've never seen, with no name to review, leaves the match unattached
    # rather than filling the review queue with nameless competitions.
    unknown = ingest(
        store,
        [game(provider_ids={"365scores": "9002"},
              kickoff_utc="2025-09-04T18:00:00+00:00",
              competition_provider_ids={"365scores": "999"})],
        country="SA",
    )
    assert store.match(unknown.match_ids[0])["competition_id"] is None
    assert [e["type"] for e in store.review_queue()] == ["team", "team"]


def test_a_team_is_never_attached_as_a_competition_by_a_shared_id(store):
    """365scores numbers leagues and clubs separately: league 649 is not club 649."""
    seed_club(store, "team:ettifaq", "Al Ettifaq", "الاتفاق", "649")

    unnamed = ingest(store, [game()], country="SA")
    assert store.match(unnamed.match_ids[0])["competition_id"] is None

    # Same collision, but now the record names the competition, so it resolves:
    # the id must not hand the resolver the club that shares the number.
    named = ingest(
        store,
        [game(provider_ids={"365scores": "9002"},
              kickoff_utc="2025-09-04T18:00:00+00:00",
              competition_name="Saudi Pro League")],
        country="SA",
    )
    competition = store.entity(store.match(named.match_ids[0])["competition_id"])
    assert (competition["type"], competition["name_en"]) == ("competition", "Saudi Pro League")


def test_provider_id_upserts_the_same_match_even_when_the_kickoff_moves(store):
    first = ingest(store, [game()], country="SA")
    moved = ingest(
        store,
        [game(kickoff_utc="2025-09-04T18:00:00+00:00", status="live")],
        country="SA",
    )

    assert moved.match_ids == first.match_ids
    assert moved.updated == 1
    assert len(matches(store)) == 1
    assert matches(store)[0]["kickoff_utc"] == "2025-09-04T18:00:00+00:00"


def test_a_second_provider_upserts_by_teams_and_kickoff_date(store):
    seed_club(store, "team:hilal", "Al Hilal", "الهلال", "5457")
    seed_club(store, "team:riyadh", "Al Riyadh", "الرياض", "5458")
    first = ingest(store, [game()], country="SA")

    # Same fixture from another feed: different match id, different kickoff
    # minute, same two clubs on the same day.
    other = ingest(
        store,
        [game(
            home_team={"name": "Al-Hilal SFC", "provider_ids": {"api_football": "2932"}},
            away_team={"name": "Al Riyadh", "provider_ids": {"api_football": "2933"}},
            kickoff_utc="2025-08-28T18:15:00+00:00",
            provider_ids={"api_football": "77001"},
            competition_provider_ids={"api_football": "307"},
        )],
        country="SA",
    )

    assert other.match_ids == first.match_ids
    assert len(matches(store)) == 1
    # Both providers' ids are now carried by the one row.
    assert json.loads(matches(store)[0]["provider_ids"]) == {
        "365scores": "9001", "api_football": "77001"}
    assert store.find_by_provider("api_football", "2932") == "team:hilal"


def test_status_climbs_the_ladder_and_never_falls_back(store):
    ingest(store, [game(status="scheduled")], country="SA")
    ingest(store, [game(status="live")], country="SA")
    assert matches(store)[0]["status"] == "live"

    ingest(store, [game(status="finished", home_score=2, away_score=1)], country="SA")
    assert matches(store)[0]["status"] == "finished"

    # A stale feed still calling the game scheduled must not un-finish it.
    stale = ingest(store, [game(status="scheduled")], country="SA")
    assert matches(store)[0]["status"] == "finished"
    assert stale.inserted == 0


def test_a_recorded_score_survives_a_resync_that_reports_none(store):
    ingest(store, [game(status="finished", home_score=2, away_score=1)], country="SA")

    ingest(store, [game(status="scheduled", home_score=None, away_score=None)],
           country="SA")

    row = matches(store)[0]
    assert (row["home_score"], row["away_score"], row["status"]) == (2, 1, "finished")


def test_a_live_score_that_moves_on_is_still_written(store):
    ingest(store, [game(status="live", home_score=1, away_score=0)], country="SA")
    ingest(store, [game(status="live", home_score=2, away_score=0)], country="SA")

    row = matches(store)[0]
    assert (row["home_score"], row["away_score"]) == (2, 0)


def test_a_stale_feed_cannot_rewind_a_finished_score(store):
    """Forward-only covers the score, not just the status ladder."""
    ingest(store, [game(status="finished", home_score=2, away_score=1)], country="SA")

    # A feed still replaying the match as live must not subtract the second goal.
    ingest(store, [game(status="live", home_score=1, away_score=0)], country="SA")

    row = matches(store)[0]
    assert (row["status"], row["home_score"], row["away_score"]) == ("finished", 2, 1)


def test_a_correction_from_an_equally_current_feed_is_written(store):
    """The deliberate allowance: a later goal is disallowed and 2-1 becomes 2-0.

    Only a feed that has caught up with the stored state may do this — the check
    is 'not behind', not 'never decreasing'.
    """
    ingest(store, [game(status="finished", home_score=2, away_score=1)], country="SA")

    ingest(store, [game(status="finished", home_score=2, away_score=0)], country="SA")

    row = matches(store)[0]
    assert (row["home_score"], row["away_score"]) == (2, 0)


def test_reingesting_the_same_payload_inserts_nothing_new(store):
    payload = [game(), game(
        home_team={"name": "Al Ittihad", "provider_ids": {"365scores": "5460"}},
        away_team={"name": "Al Nassr", "provider_ids": {"365scores": "5461"}},
        kickoff_utc="2025-08-29T18:30:00+00:00",
        provider_ids={"365scores": "9002"},
    )]
    first = ingest(store, payload, country="SA")

    def counts():
        return {table: store.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
                for table in ("matches", "entities", "aliases")}

    before = counts()
    again = ingest(store, payload, country="SA")

    assert counts() == before
    assert again.match_ids == first.match_ids
    assert (again.inserted, again.updated, again.unchanged) == (0, 0, 2)


def test_an_unstorable_record_is_rejected_rather_than_half_written(store):
    with pytest.raises(ValueError, match="kickoff_utc"):
        ingest(store, [game(kickoff_utc=None)], country="SA", strict=True)
    with pytest.raises(ValueError, match="no name"):
        ingest(store, [game(away_team={"provider_ids": {"365scores": "5458"}})],
               country="SA", strict=True)
    with pytest.raises(ValueError, match="unknown match status"):
        # A status no provider vocabulary defines: not a state to guess at.
        ingest(store, [game(status="relegated")], country="SA", strict=True)

    # Rejected means nothing was written — not the match, and not the clubs that
    # the home side had already resolved before the record was refused.
    assert matches(store) == []
    assert count(store, "entities") == 0
    assert count(store, "aliases") == 0
    assert store.review_queue() == []


def test_a_failure_after_the_first_club_resolved_rolls_that_club_back(store):
    """Validation cannot foresee everything; the transaction boundary can.

    The home club is already an entity with aliases by the time the away club is
    attempted, so a failure there must undo it rather than leave an orphan in the
    review queue for a match that was never stored.
    """
    real = Resolver(store)

    class FailsOnTheAwayClub:
        calls = 0

        def resolve(self, **kwargs):
            FailsOnTheAwayClub.calls += 1
            if FailsOnTheAwayClub.calls == 2:
                raise RuntimeError("provider lookup exploded")
            return real.resolve(**kwargs)

    result = ingest(store, [game()], country="SA", resolver=FailsOnTheAwayClub())

    assert [e.reason for e in result.errors] == ["provider lookup exploded"]
    assert (count(store, "entities"), count(store, "aliases")) == (0, 0)


def test_a_bad_record_does_not_discard_the_rest_of_the_batch(store):
    """A season is ingested in one pass; one unusable fixture is not a data loss."""
    result = ingest(
        store,
        [
            game(),
            game(status="relegated",
                 home_team={"name": "Al Feiha", "provider_ids": {"365scores": "5462"}},
                 away_team={"name": "Al Fateh", "provider_ids": {"365scores": "5463"}},
                 kickoff_utc="2025-08-29T18:00:00+00:00",
                 provider_ids={"365scores": "9003"}),
            game(kickoff_utc="2025-08-30T18:00:00+00:00",
                 provider_ids={"365scores": "9004"}),
        ],
        country="SA",
    )

    assert result.inserted == 2
    assert len(matches(store)) == 2
    # The drop is reported, never silent...
    assert [(e.index, "unknown match status" in e.reason) for e in result.errors] == [
        (1, True)]
    # ...and the refused record left nothing of itself behind.
    assert [e["name_en"] for e in store.review_queue()] == ["Al Hilal", "Al Riyadh"]


def test_provider_states_outside_the_ladder_are_mapped_not_rejected(store):
    """Real feeds emit more than three states; each collapses onto one we store."""
    postponed = ingest(store, [game(status="Postponed")], country="SA")
    assert postponed.errors == []
    assert matches(store)[0]["status"] == "scheduled"

    ingest(store, [game(status="abandoned", home_score=1, away_score=0)], country="SA")
    row = matches(store)[0]
    assert (row["status"], row["home_score"]) == ("finished", 1)


def test_a_canned_collector_payload_ingests_and_then_resyncs_clean(store):
    """The whole pipeline: canned source payload → resolver → `matches`."""
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "365scores_games.json").read_text()
    )
    client = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))

    with client:
        collector = Scores365Collector(store, client=client, window_days=31)
        first = ingest(
            store,
            collector.collect(season_start="2025-08-28", season_end="2025-09-01"),
            country="SA",
        )
        second = ingest(
            store,
            collector.collect(season_start="2025-08-28", season_end="2025-09-01"),
            country="SA",
        )

    assert first.inserted == 2
    assert (second.inserted, second.unchanged) == (0, 2)
    stored = matches(store)
    assert [(row["status"], row["home_score"], row["away_score"]) for row in stored] == [
        ("finished", 2, 1),
        ("scheduled", None, None),
    ]
    assert all(row["home_entity"].startswith("team:") for row in stored)
