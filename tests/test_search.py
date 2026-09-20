"""Name lookup reads the store — it never resolves a query into a new entity."""

import pytest

from arabfootball.resolve.search import search
from arabfootball.store.db import Store


@pytest.fixture()
def store():
    value = Store(":memory:")
    yield value
    value.close()


def _team(store, name_ar=None, name_en=None, country="SA"):
    return store.create_entity(type="team", name_ar=name_ar, name_en=name_en, country=country)


def test_search_never_creates_the_entity_it_failed_to_find(store):
    _team(store, "الهلال", "Al Hilal")
    before = store.conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]

    assert search(store, "Olympique de Marseille") == []
    after = store.conn.execute("SELECT COUNT(*) AS n FROM entities").fetchone()["n"]
    assert (after, store.review_queue()) == (before, [])


def test_exact_normalized_hits_outrank_weaker_ones(store):
    exact = _team(store, "الهلال", "Al Hilal")
    partial = _team(store, "الهلال الساحلي", "Al Hilal Al Sahili")

    results = search(store, "Al-Hilal")

    assert [r["id"] for r in results] == [exact, partial]
    assert [r["method"] for r in results] == ["exact", "partial"]


def test_a_doubled_latin_consonant_still_meets_its_arabic_spelling(store):
    """A shadda is one Arabic letter and two Latin ones: الاتحاد / Al-Ittihad."""
    ittihad = _team(store, "الاتحاد")

    results = search(store, "Al-Ittihad")

    assert [(r["id"], r["method"]) for r in results] == [(ittihad, "cross_script")]


def test_fuzzy_survives_transliteration_noise_but_stays_bounded(store):
    ittifaq = _team(store, "الاتفاق", "Al Ittifaq")

    assert [r["id"] for r in search(store, "Al Ittifak")] == [ittifaq]
    # A different club in the same league is not a near-miss of this one.
    assert search(store, "Al Khaleej") == []


def test_short_names_never_match_on_the_cross_script_skeleton(store):
    """"Al Ahli" reduces to a two-letter skeleton — too little to identify a club."""
    _team(store, "الأهلي", "Al Ahli", country="SA")
    jordan = _team(store, "الأهلي", "Al Ahli", country="JO")

    assert [r["id"] for r in search(store, "الأهلي", country="JO")] == [jordan]
    assert search(store, "Al Hala", country="JO") == []


def test_limit_caps_the_result_list(store):
    for index in range(5):
        _team(store, None, f"Al Hilal {index}")

    assert len(search(store, "Al Hilal", limit=2)) == 2
    assert search(store, "Al Hilal", limit=0) == []
