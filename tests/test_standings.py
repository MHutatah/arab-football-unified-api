import json
from pathlib import Path

import httpx
import pytest

from arabfootball.collectors.ingest import ingest
from arabfootball.collectors.scores365 import Scores365Collector
from arabfootball.collectors.standings import (
    SAUDI_PRO_LEAGUE,
    StandingsCollector,
    seed_league,
)
from arabfootball.store.db import Store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def store():
    value = Store(":memory:")
    yield value
    value.close()


def standings_payload():
    return json.loads((FIXTURES / "365scores_standings.json").read_text())


def games_payload():
    return json.loads((FIXTURES / "365scores_games.json").read_text())


def canned(payload, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def collect_standings(store, requests=None):
    with canned(standings_payload(), requests) as client:
        return StandingsCollector(store, client=client).collect()


def collect_payload(store, payload):
    """Collect an arbitrary standings shape, for the parsing edge cases."""
    with canned(payload) as client:
        return StandingsCollector(store, client=client).collect()


def group(*rows):
    return {"standings": [{"competitionId": 649, "rows": list(rows)}]}


def ingest_fixtures(store):
    with canned(games_payload()) as client:
        collector = Scores365Collector(store, client=client, window_days=31)
        return ingest(
            store,
            collector.collect(season_start="2025-08-28", season_end="2025-09-01"),
            country="SA",
        )


def teams(store):
    return [dict(r) for r in store.conn.execute(
        "SELECT * FROM entities WHERE type='team' ORDER BY name_en")]


def test_the_standings_table_is_collected_as_one_record_per_club(store):
    requests = []
    records = collect_standings(store, requests)

    assert [request.url.path for request in requests] == ["/web/standings/"]
    assert dict(requests[0].url.params) == {"competitions": "649"}
    assert len(records) == 18
    # Table order, so the seed reads like the league table it came from.
    assert [record["position"] for record in records] == list(range(1, 19))
    assert records[0] == {
        "name": "Al Hilal",
        "provider_ids": {"365scores": "5457"},
        "position": 1,
        "competition_provider_ids": {"365scores": "649"},
    }
    assert store.conn.execute("SELECT status FROM source_runs").fetchone()["status"] == "ok"


def test_a_flat_row_is_read_from_its_own_competitor_fields(store):
    """Not every group nests a `competitor`; some carry the club fields inline."""
    records = collect_payload(store, group(
        {"position": 1, "competitorId": 5457, "competitorName": "Al Hilal"}))

    assert records == [{
        "name": "Al Hilal",
        "provider_ids": {"365scores": "5457"},
        "position": 1,
        "competition_provider_ids": {"365scores": "649"},
    }]


def test_a_flat_row_carrying_the_nested_field_names_is_read_from_the_row(store):
    """The other flat shape: `id`/`name` at the top level, no `competitor` at all."""
    records = collect_payload(store, group({"position": 1, "id": 5457, "name": "Al Hilal"}))

    assert records[0]["name"] == "Al Hilal"
    assert records[0]["provider_ids"] == {"365scores": "5457"}


def test_a_nonmapping_competitor_falls_back_to_the_row(store):
    records = collect_payload(store, group(
        {"position": 2, "competitor": None, "competitorId": 5461,
         "competitorName": "Al Nassr"}))

    assert records[0]["name"] == "Al Nassr"
    assert records[0]["provider_ids"] == {"365scores": "5461"}


def test_a_row_that_ranks_instead_of_positioning_is_still_placed(store):
    records = collect_payload(store, group(
        {"rank": 2, "competitor": {"id": 5461, "name": "Al Nassr"}},
        {"rank": 1, "competitor": {"id": 5457, "name": "Al Hilal"}}))

    assert [record["position"] for record in records] == [1, 2]
    assert [record["name"] for record in records] == ["Al Hilal", "Al Nassr"]


def test_a_row_with_no_usable_position_sorts_last(store):
    records = collect_payload(store, group(
        {"position": None, "competitor": {"id": 5461, "name": "Al Nassr"}},
        {"position": "not a number", "competitor": {"id": 5460, "name": "Al Ittihad"}},
        {"position": 1, "competitor": {"id": 5457, "name": "Al Hilal"}}))

    assert records[0]["name"] == "Al Hilal"
    assert {record["name"] for record in records[1:]} == {"Al Nassr", "Al Ittihad"}
    assert [record["position"] for record in records] == [1, None, None]


def test_a_club_listed_twice_is_collected_once(store):
    """A promotion/relegation group can repeat a club; seeding it twice would
    make the second pass a duplicate rather than a no-op."""
    records = collect_payload(store, group(
        {"position": 1, "competitor": {"id": 5457, "name": "Al Hilal"}},
        {"position": 1, "competitor": {"id": 5457, "name": "Al-Hilal SFC"}}))

    assert len(records) == 1
    assert records[0]["name"] == "Al Hilal"  # the first spelling wins


def test_every_group_of_a_multigroup_table_is_collected(store):
    records = collect_payload(store, {"standings": [
        {"name": "Group A", "rows": [
            {"position": 1, "competitor": {"id": 5457, "name": "Al Hilal"}}]},
        {"name": "Group B", "rows": [
            {"position": 1, "competitor": {"id": 5461, "name": "Al Nassr"}}]},
        {"name": "no rows at all"},
    ]})

    assert {record["name"] for record in records} == {"Al Hilal", "Al Nassr"}


def test_a_single_standings_group_outside_a_list_is_accepted(store):
    records = collect_payload(store, {"standings": {
        "competitionId": 649,
        "rows": [{"position": 1, "competitor": {"id": 5457, "name": "Al Hilal"}}]}})

    assert [record["name"] for record in records] == ["Al Hilal"]


def test_a_standings_response_that_is_not_an_object_fails_soft(store):
    assert collect_payload(store, ["not", "an", "object"]) == []

    run = store.conn.execute("SELECT status, errors FROM source_runs").fetchone()
    assert run["status"] == "failed"
    assert "not an object" in json.loads(run["errors"])[0]["message"]


def test_a_row_without_a_usable_competitor_fails_soft(store):
    assert collect_payload(store, group({"position": 1, "competitor": {"id": 5457}})) == []

    run = store.conn.execute("SELECT status, errors FROM source_runs").fetchone()
    assert run["status"] == "failed"
    assert "invalid competitor" in json.loads(run["errors"])[0]["message"]


def test_a_nonmapping_row_fails_soft(store):
    assert collect_payload(store, group("Al Hilal")) == []

    run = store.conn.execute("SELECT status, errors FROM source_runs").fetchone()
    assert run["status"] == "failed"
    assert "invalid row" in json.loads(run["errors"])[0]["message"]


def test_a_standings_payload_without_rows_fails_soft(store):
    with canned({"standings": []}) as client:
        assert StandingsCollector(store, client=client).collect() == []

    run = store.conn.execute("SELECT status, errors FROM source_runs").fetchone()
    assert run["status"] == "failed"
    assert "rows[]" in json.loads(run["errors"])[0]["message"]


def test_seeding_creates_the_competition_with_both_names_and_all_eighteen_clubs(store):
    result = seed_league(store, collect_standings(store))

    competition = store.entity(result.competition_id)
    assert (competition["type"], competition["country"]) == ("competition", "SA")
    assert competition["name_en"] == SAUDI_PRO_LEAGUE.name_en
    assert competition["name_ar"] == SAUDI_PRO_LEAGUE.name_ar
    assert competition["provisional"] == 0
    assert store.find_by_provider("365scores", "649") == result.competition_id

    assert len(result.team_ids) == len(set(result.team_ids)) == 18
    assert result.created == 19  # the competition and all eighteen clubs
    assert result.promoted == 0
    # Nothing seeded is a guess, so nothing seeded needs review.
    assert store.review_queue() == []
    assert [club["name_en"] for club in teams(store)][:3] == [
        "Al Ahli", "Al Ettifaq", "Al Fateh"]

    # Every club carries the provider's own id, which is what the next fixture
    # ingest resolves on.
    for record in collect_standings(store):
        entity_id = store.find_by_provider("365scores", record["provider_ids"]["365scores"])
        assert entity_id in result.team_ids
        assert store.entity(entity_id)["name_en"] == record["name"]


def test_reseeding_a_seeded_league_changes_nothing(store):
    first = seed_league(store, collect_standings(store))

    def counts():
        return {table: store.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
                for table in ("entities", "aliases")}

    before = counts()
    again = seed_league(store, collect_standings(store))

    assert counts() == before
    assert again.team_ids == first.team_ids
    assert again.competition_id == first.competition_id
    assert (again.created, again.promoted) == (0, 0)


def test_seeding_promotes_the_provisionals_an_earlier_ingest_left_behind(store):
    ingest_fixtures(store)
    assert len(store.review_queue()) == 4

    result = seed_league(store, collect_standings(store))

    # The four clubs the fixtures invented are the seeded ones, not duplicates.
    assert len(teams(store)) == 18
    assert result.promoted == 4
    assert result.created == 15  # the competition and the fourteen unseen clubs
    assert store.find_by_provider("365scores", "5457") in result.team_ids
    assert store.review_queue() == []


def test_a_reseed_keeps_a_recorded_name_and_learns_its_own_spelling(store):
    """A maintainer's spelling outranks the feed's; the feed's becomes an alias."""
    store.conn.execute(
        "INSERT INTO entities (id,type,name_en,name_ar,country,provisional,created_at)"
        " VALUES ('team:hilal','team','Al-Hilal SFC','الهلال','SA',0,"
        "'2025-01-01T00:00:00+00:00')")
    store.conn.commit()
    store.add_alias("team:hilal", "365scores", "5457", "Al-Hilal SFC", "en")

    result = seed_league(store, collect_standings(store))

    assert "team:hilal" in result.team_ids
    assert (result.created, result.promoted) == (18, 0)  # the competition + 17 clubs
    assert store.entity("team:hilal")["name_en"] == "Al-Hilal SFC"
    assert store.find_by_provider("365scores", "5457") == "team:hilal"
    assert "Al Hilal" in {row["name_variant"] for row in store.conn.execute(
        "SELECT name_variant FROM aliases WHERE entity_id='team:hilal'")}


def test_a_club_record_without_the_provider_id_is_refused(store):
    with pytest.raises(ValueError, match="365scores id"):
        seed_league(store, [{"name": "Al Hilal", "provider_ids": {}}])


def test_seeding_first_leaves_a_fixture_ingest_with_nothing_provisional(store):
    """The point of the module: seed, and the same ingest stops guessing."""
    seed_league(store, collect_standings(store))

    result = ingest_fixtures(store)

    # Two fixtures, four clubs and the league — every one of them canonical,
    # and the league attached rather than left NULL.
    assert len(result.match_ids) == 2
    assert _ingested_entities(store, result) == 5
    assert store.review_queue() == []


def test_the_same_ingest_without_seeding_leaves_every_club_provisional(store):
    result = ingest_fixtures(store)

    # No seed: four provisional clubs, and no competition to attach at all.
    assert _ingested_entities(store, result) == 4
    assert len(store.review_queue()) == 4


def _ingested_entities(store, result) -> int:
    """How many distinct entities the ingested matches point at."""
    entity_ids = set()
    for match_id in result.match_ids:
        row = store.match(match_id)
        entity_ids.update(
            row[column] for column in ("home_entity", "away_entity", "competition_id")
            if row[column])
    return len(entity_ids)
