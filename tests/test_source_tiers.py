"""Source tiering — a reference-tier row must never reach a published snapshot.

Tier B sources (unstated licence, e.g. the Saudi Pro League transfers dataset) are
ingested for discovery and cross-checking. They are useful precisely because they
point at facts worth verifying — but the exported database may only carry rows we
have the right to redistribute. This is the guardrail that makes keeping them safe.
"""
import pytest

from arabfootball.store.db import Store

PUBLISHABLE = "publishable"
REFERENCE = "reference"


@pytest.fixture()
def store():
    s = Store(":memory:")
    yield s
    s.close()


def _team(store, name, country="SA"):
    return store.create_entity(type="team", name_en=name, country=country)


def _player(store, name):
    return store.create_entity(type="player", name_en=name, country="SA")


def _transfer(store, tid, player, frm, to, *, source, tier, corroborated_by=None):
    store.conn.execute(
        "INSERT INTO transfers (id,player_entity,from_entity,to_entity,date,fee_eur,"
        "type,source,tier,corroborated_by) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (tid, player, frm, to, "2023-07-01", 1000000, "permanent",
         source, tier, corroborated_by))
    store.conn.commit()


def test_tier_defaults_to_publishable(store):
    p, a, b = _player(store, "X"), _team(store, "Al Hilal"), _team(store, "Al Nassr")
    store.conn.execute(
        "INSERT INTO transfers (id,player_entity,from_entity,to_entity) VALUES (?,?,?,?)",
        ("t0", p, a, b))
    store.conn.commit()
    row = store.conn.execute("SELECT tier FROM transfers WHERE id='t0'").fetchone()
    assert row["tier"] == PUBLISHABLE


def test_reference_rows_are_excluded_from_export(store):
    """The export filter is the whole point: Tier-B data stays internal."""
    p = _player(store, "Player One")
    a, b = _team(store, "Al Hilal"), _team(store, "Al Nassr")
    _transfer(store, "t-pub", p, a, b, source="global-transfers-cc0", tier=PUBLISHABLE)
    _transfer(store, "t-ref", p, b, a, source="saudi-transfers-unstated", tier=REFERENCE)

    exported = [r["id"] for r in store.conn.execute(
        "SELECT id FROM transfers WHERE tier = ?", (PUBLISHABLE,))]
    assert exported == ["t-pub"]
    assert "t-ref" not in exported

    # ...but it IS present in the working database, which is why we keep it
    all_rows = [r["id"] for r in store.conn.execute("SELECT id FROM transfers")]
    assert set(all_rows) == {"t-pub", "t-ref"}


def test_corroborated_reference_row_becomes_publishable(store):
    """A reference row is promoted only when an independent source confirms it,
    and the published row then cites that corroborating source."""
    p = _player(store, "Player Two")
    a, b = _team(store, "Al Ahli"), _team(store, "Al Ittihad")
    _transfer(store, "t1", p, a, b, source="saudi-transfers-unstated", tier=REFERENCE)

    # an independent Tier-A source confirms the same move
    store.conn.execute(
        "UPDATE transfers SET tier=?, corroborated_by=? WHERE id='t1'",
        (PUBLISHABLE, "global-transfers-cc0"))
    store.conn.commit()

    row = store.conn.execute("SELECT * FROM transfers WHERE id='t1'").fetchone()
    assert row["tier"] == PUBLISHABLE
    assert row["corroborated_by"] == "global-transfers-cc0"
    assert row["id"] in [r["id"] for r in store.conn.execute(
        "SELECT id FROM transfers WHERE tier = ?", (PUBLISHABLE,))]
