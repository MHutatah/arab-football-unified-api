"""The bundled `/v1` read server answers from the snapshot alone.

Every case here runs against a real SQLite file seeded with real Arabic
spellings — the API is the surface where a bilingual identity either survives or
quietly becomes an English-only one.
"""

import pytest
from fastapi.testclient import TestClient

from arabfootball.api.main import create_app
from arabfootball.resolve.review import merge
from arabfootball.store.db import Store

SPL = "competition:spl"
HILAL = "team:hilal"
NASSR = "team:nassr"
SUDAN_HILAL = "team:hilal-omdurman"
ITTIHAD = "team:ittihad"
SALEM = "player:salem"


def _entity(store, entity_id, type, name_ar, name_en, country, provisional=0):
    store.conn.execute(
        "INSERT INTO entities (id,type,name_ar,name_en,country,provisional,created_at)"
        " VALUES (?,?,?,?,?,?,'2025-01-01T00:00:00+00:00')",
        (entity_id, type, name_ar, name_en, country, provisional))
    store.conn.commit()
    return entity_id


def _match(store, match_id, home, away, kickoff, home_score, away_score, *,
           status="finished", competition=SPL):
    store.conn.execute(
        "INSERT INTO matches (id,competition_id,season,home_entity,away_entity,kickoff_utc,"
        "status,home_score,away_score,provider_ids)"
        " VALUES (?,?,'2024/25',?,?,?,?,?,?,?)",
        (match_id, competition, home, away, kickoff, status, home_score, away_score,
         '{"365scores": "9001"}'))
    store.conn.commit()


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "snapshot.db")


@pytest.fixture()
def store(db_path):
    """A snapshot holding the Saudi clubs, their Sudanese namesake, and history."""
    value = Store(db_path)
    _entity(value, SPL, "competition", "دوري روشن السعودي", "Saudi Pro League", "SA")
    _entity(value, HILAL, "team", "الهلال", "Al Hilal", "SA")
    _entity(value, NASSR, "team", "النصر", "Al Nassr", "SA")
    # The namesake that every commercial feed confuses with the Saudi club.
    _entity(value, SUDAN_HILAL, "team", "الهلال", "Al Hilal Omdurman", "SD")
    # Stored in Arabic only: a Latin query still has to find it.
    _entity(value, ITTIHAD, "team", "الاتحاد", None, "SA")
    _entity(value, SALEM, "player", "سالم الدوسري", "Salem Al-Dawsari", "SA")

    _match(value, "match:1", HILAL, NASSR, "2024-08-10T18:00:00+00:00", 3, 1)
    _match(value, "match:2", NASSR, HILAL, "2024-12-20T18:00:00+00:00", 2, 2)
    _match(value, "match:3", HILAL, NASSR, "2025-03-15T18:00:00+00:00", 0, 1)
    _match(value, "match:4", HILAL, NASSR, "2025-09-30T18:00:00+00:00", None, None,
           status="scheduled")
    # A friendly outside the league: the competition filter must exclude it.
    _match(value, "match:5", HILAL, SUDAN_HILAL, "2025-01-05T18:00:00+00:00", 1, 0,
           competition=None)
    yield value
    value.close()


@pytest.fixture()
def client(store, db_path):
    with TestClient(create_app(db_path)) as test_client:
        yield test_client


# ── /v1/search ──────────────────────────────────────────────────────────────
def test_search_resolves_an_arabic_name_to_the_club_stored_in_english(client):
    body = client.get("/v1/search", params={"q": "الهلال", "country": "SA"}).json()

    assert [r["id"] for r in body["results"]] == [HILAL]
    assert body["results"][0]["name_en"] == "Al Hilal"
    assert body["count"] == 1


def test_search_resolves_a_latin_spelling_to_the_club_stored_in_arabic(client):
    body = client.get("/v1/search", params={"q": "Al-Ittihad"}).json()

    hit = next(r for r in body["results"] if r["id"] == ITTIHAD)
    assert (hit["name_ar"], hit["name_en"]) == ("الاتحاد", None)
    assert hit["method"] == "cross_script"


def test_search_scopes_namesakes_by_country(client):
    everywhere = client.get("/v1/search", params={"q": "Al Hilal"}).json()
    saudi_only = client.get("/v1/search", params={"q": "Al Hilal", "country": "SA"}).json()

    assert {r["id"] for r in everywhere["results"]} == {HILAL, SUDAN_HILAL}
    assert [r["id"] for r in saudi_only["results"]] == [HILAL]
    # Exact beats partial: the club actually called "Al Hilal" leads.
    assert everywhere["results"][0]["id"] == HILAL


def test_search_narrows_by_type_and_finds_a_player_in_either_script(client):
    body = client.get("/v1/search", params={"q": "الدوسري", "type": "player"}).json()

    assert [r["id"] for r in body["results"]] == [SALEM]
    assert body["results"][0]["name_en"] == "Salem Al-Dawsari"


def test_search_finds_a_learned_alias_spelling(client, store):
    store.add_alias(NASSR, "365scores", "5471", "Al-Nassr FC", "en")

    body = client.get("/v1/search", params={"q": "Al-Nassr FC"}).json()

    assert [r["id"] for r in body["results"]] == [NASSR]


def test_search_returns_no_results_rather_than_a_guess(client):
    body = client.get("/v1/search", params={"q": "Manchester United"}).json()

    assert (body["count"], body["results"]) == (0, [])


def test_every_search_result_carries_both_name_fields(client):
    body = client.get("/v1/search", params={"q": "الهلال"}).json()

    assert body["results"]
    for result in body["results"]:
        assert "name_ar" in result and "name_en" in result


# ── /v1/teams/{id} ──────────────────────────────────────────────────────────
def test_team_profile_returns_both_names_and_derived_form(client):
    body = client.get(f"/v1/teams/{HILAL}").json()

    assert (body["id"], body["name_ar"], body["name_en"]) == (HILAL, "الهلال", "Al Hilal")
    assert body["country"] == "SA"
    form = body["form"]
    # Newest first, scheduled fixtures excluded: L (0-1), W (1-0), D (2-2), W (3-1).
    assert [m["id"] for m in form["matches"]] == ["match:3", "match:5", "match:2", "match:1"]
    assert (form["played"], form["wins"], form["draws"], form["losses"]) == (4, 2, 1, 1)
    assert form["points"] == 7


def test_team_form_length_is_a_caller_choice(client):
    body = client.get(f"/v1/teams/{HILAL}", params={"form": 2}).json()

    assert [m["id"] for m in body["form"]["matches"]] == ["match:3", "match:5"]
    assert body["form"]["played"] == 2


def test_unknown_team_id_is_404_with_a_clear_message(client):
    response = client.get("/v1/teams/team:does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown team: team:does-not-exist"


def test_an_id_of_another_type_is_404_that_says_what_it_is(client):
    response = client.get(f"/v1/teams/{SALEM}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"unknown team: {SALEM} is a player"


def test_a_merged_away_id_is_404_pointing_at_the_club_that_absorbed_it(client, store):
    provisional = _entity(store, "team:prov", "team", "الهلال السعودي", None, "SA", 1)
    merge(store, provisional, HILAL)

    response = client.get(f"/v1/teams/{provisional}")

    assert response.status_code == 404
    assert response.json()["detail"] == f"{provisional} was merged into {HILAL}"


# ── /v1/matches ─────────────────────────────────────────────────────────────
def test_matches_filter_by_competition(client):
    body = client.get("/v1/matches", params={"competition": SPL}).json()

    assert [m["id"] for m in body["matches"]] == ["match:1", "match:2", "match:3", "match:4"]
    assert body["count"] == 4


def test_matches_filter_by_an_inclusive_date_window(client):
    body = client.get("/v1/matches", params={"from": "2024-12-20", "to": "2025-01-05"}).json()

    # Both bounds land exactly on a kickoff day and both are included.
    assert [m["id"] for m in body["matches"]] == ["match:2", "match:5"]


def test_matches_combine_competition_and_window(client):
    body = client.get(
        "/v1/matches",
        params={"competition": SPL, "from": "2025-01-01", "to": "2025-06-30"}).json()

    assert [m["id"] for m in body["matches"]] == ["match:3"]
    assert body["filters"] == {"competition": SPL, "from": "2025-01-01", "to": "2025-06-30"}


def test_matches_are_chronological_and_pageable(client):
    every = client.get("/v1/matches").json()
    page = client.get("/v1/matches", params={"limit": 2, "offset": 1}).json()

    assert [m["id"] for m in every["matches"]] == [
        "match:1", "match:2", "match:5", "match:3", "match:4"]
    assert [m["id"] for m in page["matches"]] == ["match:2", "match:5"]


def test_match_rows_expose_provider_ids_as_json(client):
    body = client.get("/v1/matches", params={"competition": SPL, "limit": 1}).json()

    assert body["matches"][0]["provider_ids"] == {"365scores": "9001"}


def test_unknown_competition_id_is_404_with_a_clear_message(client):
    response = client.get("/v1/matches", params={"competition": "competition:nope"})

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown competition: competition:nope"


def test_a_malformed_date_window_is_rejected_not_silently_ignored(client):
    response = client.get("/v1/matches", params={"from": "last tuesday"})

    assert response.status_code == 400
    assert "ISO date" in response.json()["detail"]


# ── /v1/h2h ─────────────────────────────────────────────────────────────────
def test_h2h_returns_the_derived_record_from_a_perspective(client):
    body = client.get("/v1/h2h", params={"a": HILAL, "b": NASSR}).json()

    assert [m["id"] for m in body["meetings"]] == ["match:3", "match:2", "match:1"]
    assert body["summary"] == {"wins": 1, "draws": 1, "losses": 1}
    assert (body["a"]["name_ar"], body["b"]["name_ar"]) == ("الهلال", "النصر")

    reversed_body = client.get("/v1/h2h", params={"a": NASSR, "b": HILAL}).json()
    assert reversed_body["summary"] == {"wins": 1, "draws": 1, "losses": 1}


def test_h2h_between_clubs_that_never_met_is_an_empty_record(client):
    body = client.get("/v1/h2h", params={"a": NASSR, "b": SUDAN_HILAL}).json()

    assert body["meetings"] == []
    assert body["summary"] == {"wins": 0, "draws": 0, "losses": 0}


def test_h2h_with_an_unknown_id_is_404_with_a_clear_message(client):
    response = client.get("/v1/h2h", params={"a": HILAL, "b": "team:ghost"})

    assert response.status_code == 404
    assert response.json()["detail"] == "unknown team: team:ghost"


def test_h2h_of_a_club_against_itself_is_refused(client):
    response = client.get("/v1/h2h", params={"a": HILAL, "b": HILAL})

    assert response.status_code == 400
    assert HILAL in response.json()["detail"]


# ── wiring ──────────────────────────────────────────────────────────────────
def test_a_missing_snapshot_says_how_to_get_one(tmp_path):
    missing = str(tmp_path / "nothing-here.db")
    with TestClient(create_app(missing)) as client:
        response = client.get("/v1/search", params={"q": "الهلال"})

    assert response.status_code == 503
    assert "make pull-db" in response.json()["detail"]


def test_the_server_never_creates_the_snapshot_it_reads(tmp_path):
    """A read API that conjures an empty database answers every query wrongly."""
    missing = tmp_path / "nothing-here.db"
    with TestClient(create_app(str(missing))) as client:
        client.get(f"/v1/teams/{HILAL}")

    assert not missing.exists()
