"""Entity resolution — the bugs this project exists to prevent."""
import pytest

from arabfootball.resolve.normalize import norm, similarity
from arabfootball.resolve.resolver import Resolver
from arabfootball.store.db import Store


@pytest.fixture()
def store():
    s = Store(":memory:")
    yield s
    s.close()


@pytest.fixture()
def resolver(store):
    return Resolver(store)


# ── normalization ───────────────────────────────────────────────────────────
def test_arabic_variants_normalize_together():
    # definite article, diacritics and letter variants must not split one club
    assert norm("الهلال") == norm("هلال")
    assert norm("الأهلي") == norm("الاهلي")


def test_latin_variants_normalize_together():
    assert norm("Al-Hilal") == norm("Al Hilal") == norm("AlHilal SFC") == norm("Hilal")
    assert norm("Al Ahli") == norm("Al-Ahly FC")


def test_similarity_tolerates_transliteration_noise():
    assert similarity("Al-Faisaly", "Al Faysaly") > 0.7
    assert similarity("Al Hilal", "Al Nassr") < 0.5


# ── resolution ──────────────────────────────────────────────────────────────
def test_provider_id_is_authoritative(resolver, store):
    first = resolver.resolve(type="team", provider="365scores", provider_id=5457,
                             name="Al Hilal Riyadh", country="SA")
    again = resolver.resolve(type="team", provider="365scores", provider_id=5457,
                             name="totally different label", country="SA")
    assert again.entity_id == first.entity_id
    assert again.method == "provider_id"


def test_same_club_across_providers_and_scripts_is_one_entity(resolver):
    a = resolver.resolve(type="team", provider="365scores", provider_id=5457,
                         name="Al Hilal", country="SA")
    b = resolver.resolve(type="team", provider="espn", provider_id=929,
                         name="Al-Hilal", country="SA")          # different provider+spelling
    c = resolver.resolve(type="team", provider="arabfootball", name="الهلال", country="SA")
    assert a.entity_id == b.entity_id == c.entity_id


def test_wrong_country_namesake_never_matches(resolver):
    """THE bug this project exists for: 'Al Hilal' the Saudi club must never
    resolve to Al Hilal Omdurman (Sudan) or Al Hilal Juba (South Sudan)."""
    saudi = resolver.resolve(type="team", provider="espn", provider_id=929,
                             name="Al Hilal", country="SA")
    sudan = resolver.resolve(type="team", provider="espn", provider_id=8080,
                             name="Al Hilal", country="SD")
    assert saudi.entity_id != sudan.entity_id


def test_al_ahli_namesakes_stay_separate(resolver):
    """Three 'Al Ahli's in three countries — the case that produced a Jordanian
    club's form in a Saudi debate."""
    ids = {c: resolver.resolve(type="team", provider="p", name="Al Ahli", country=c).entity_id
           for c in ("SA", "JO", "EG")}
    assert len(set(ids.values())) == 3


def test_unmatched_becomes_provisional_not_a_guess(resolver, store):
    r = resolver.resolve(type="team", provider="x", name="Some Unknown FC", country="SA")
    assert r.provisional and r.method == "created"
    assert any(e["id"] == r.entity_id for e in store.review_queue())


def test_learned_aliases_make_the_next_pass_exact(resolver, store):
    first = resolver.resolve(type="team", provider="365scores", provider_id=5457,
                             name="Al Hilal Riyadh", country="SA")
    # a different provider, no id, using the spelling we learned
    second = resolver.resolve(type="team", provider="rss", name="Al Hilal Riyadh",
                              country="SA")
    assert second.entity_id == first.entity_id
    assert second.method == "name"
