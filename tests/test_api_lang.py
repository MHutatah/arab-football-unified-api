"""The read API answers in both scripts, and `?lang=` picks the display name.

Real Arabic strings throughout: a placeholder would hide exactly the fallback
and encoding problems these assertions exist to catch.
"""

import pytest
from fastapi.testclient import TestClient

from arabfootball.api.lang import display_name, entity_payload, parse_lang
from arabfootball.api.main import create_app
from arabfootball.store.db import Store


@pytest.fixture()
def store():
    # The API serves from a threadpool, so its store is opened thread-shared.
    database = Store(":memory:", check_same_thread=False)
    yield database
    database.close()


@pytest.fixture()
def client(store):
    return TestClient(create_app(store))


@pytest.fixture()
def hilal(store):
    return store.create_entity(type="team", name_ar="الهلال", name_en="Al Hilal",
                               country="SA")


# ── entity payloads ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("query", ["", "?lang=ar", "?lang=en"])
def test_both_names_are_always_present_whatever_the_language(client, hilal, query):
    body = client.get(f"/v1/teams/{hilal}{query}").json()

    assert body["name_ar"] == "الهلال"
    assert body["name_en"] == "Al Hilal"


def test_arabic_is_the_default_display_language(client, hilal):
    body = client.get(f"/v1/teams/{hilal}").json()

    assert body["lang"] == "ar"
    assert body["display_name"] == "الهلال"


def test_lang_en_switches_the_display_name(client, hilal):
    body = client.get(f"/v1/teams/{hilal}?lang=en").json()

    assert body["lang"] == "en"
    assert body["display_name"] == "Al Hilal"


def test_lang_ar_is_explicitly_accepted_too(client, hilal):
    body = client.get(f"/v1/teams/{hilal}?lang=ar").json()

    assert body["display_name"] == "الهلال"


# ── fallback: never a null display name ─────────────────────────────────────
def test_a_missing_arabic_name_falls_back_to_the_latin_one(client, store):
    # Transliteration-only club: the Arabic spelling hasn't been collected yet.
    team = store.create_entity(type="team", name_en="Al Faisaly", country="SA")

    body = client.get(f"/v1/teams/{team}").json()

    assert body["name_ar"] is None
    assert body["display_name"] == "Al Faisaly"


def test_a_missing_english_name_falls_back_to_the_arabic_one(client, store):
    team = store.create_entity(type="team", name_ar="الاتحاد", country="SA")

    body = client.get(f"/v1/teams/{team}?lang=en").json()

    assert body["name_en"] is None
    assert body["display_name"] == "الاتحاد"


def test_a_blank_translation_counts_as_missing():
    assert display_name("   ", "Al Nassr", "ar") == "Al Nassr"
    assert display_name("النصر", "", "en") == "النصر"


def test_display_name_is_null_only_when_there_is_no_name_at_all():
    assert display_name(None, None, "ar") is None
    assert display_name(None, None, "en") is None


# ── the ?lang= parameter itself ─────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    (None, "ar"),
    ("", "ar"),
    ("  ", "ar"),
    ("ar", "ar"),
    ("en", "en"),
    ("EN", "en"),
    (" Ar ", "ar"),
    ("ar-SA", "ar"),   # apps pass whatever locale their UI is set to
    ("en_GB", "en"),
])
def test_parse_lang_normalizes_locale_tags_and_casing(raw, expected):
    assert parse_lang(raw) == expected


def test_a_locale_tag_works_over_http_too(client, hilal):
    body = client.get(f"/v1/teams/{hilal}?lang=en-GB").json()

    assert body["display_name"] == "Al Hilal"


def test_an_unsupported_language_is_refused_with_a_clear_message(client, hilal):
    response = client.get(f"/v1/teams/{hilal}?lang=fr")

    assert response.status_code == 400
    assert "ar, en" in response.json()["detail"]


def test_parse_lang_rejects_a_language_we_hold_no_names_in():
    with pytest.raises(ValueError, match="unsupported lang"):
        parse_lang("fr")


# ── search results are entity payloads too ──────────────────────────────────
def test_search_matches_either_script_and_returns_both_names(client, store, hilal):
    store.create_entity(type="team", name_ar="النصر", name_en="Al Nassr", country="SA")

    for term in ("الهلال", "Al Hilal"):
        body = client.get("/v1/search", params={"q": term}).json()

        assert [r["id"] for r in body["results"]] == [hilal]
        assert body["results"][0]["name_ar"] == "الهلال"
        assert body["results"][0]["name_en"] == "Al Hilal"
        assert body["results"][0]["display_name"] == "الهلال"


def test_search_display_names_follow_lang(client, store, hilal):
    body = client.get("/v1/search", params={"q": "الهلال", "lang": "en"}).json()

    assert body["lang"] == "en"
    assert [r["display_name"] for r in body["results"]] == ["Al Hilal"]


def test_search_results_fall_back_rather_than_return_a_null_display_name(client, store):
    store.create_entity(type="team", name_ar="الوحدة", country="SA")

    body = client.get("/v1/search", params={"q": "الوحدة", "lang": "en"}).json()

    assert [r["display_name"] for r in body["results"]] == ["الوحدة"]


def test_search_can_be_scoped_by_type_and_country(client, store):
    saudi = store.create_entity(type="team", name_ar="الهلال", name_en="Al Hilal",
                                country="SA")
    store.create_entity(type="team", name_ar="الهلال", name_en="Al Hilal",
                        country="SD")  # the Sudanese namesake

    body = client.get("/v1/search", params={"q": "Al Hilal", "type": "team",
                                            "country": "SA"}).json()

    assert [r["id"] for r in body["results"]] == [saudi]


def test_search_of_an_unusable_query_finds_nothing(client, hilal):
    body = client.get("/v1/search", params={"q": "   "}).json()

    assert body["count"] == 0


# ── plumbing the payloads rest on ───────────────────────────────────────────
def test_entity_payload_decodes_meta_and_flags_provisional(store):
    team = store.create_entity(type="team", name_ar="الرياض", country="SA",
                               meta={"founded": 1953}, provisional=True)

    payload = entity_payload(store.entity(team), "ar")

    assert payload["meta"] == {"founded": 1953}
    assert payload["provisional"] is True
    assert payload["country"] == "SA"


def test_an_unknown_or_non_team_id_is_a_404(client, store):
    player = store.create_entity(type="player", name_ar="سالم الدوسري", country="SA")

    assert client.get("/v1/teams/team:missing").status_code == 404
    assert client.get(f"/v1/teams/{player}").status_code == 404
    assert "no team" in client.get("/v1/teams/team:missing").json()["detail"]


def test_the_server_opens_the_snapshot_named_by_the_environment(tmp_path, monkeypatch):
    """`make serve` passes no store: the app opens the downloaded snapshot itself."""
    snapshot = tmp_path / "arabfootball.db"
    producer = Store(str(snapshot))
    producer.create_entity(type="team", name_ar="الشباب", name_en="Al Shabab",
                           country="SA")
    producer.close()
    monkeypatch.setenv("ARABFOOTBALL_DB", str(snapshot))

    body = TestClient(create_app()).get("/v1/search", params={"q": "الشباب"}).json()

    assert [r["display_name"] for r in body["results"]] == ["الشباب"]
