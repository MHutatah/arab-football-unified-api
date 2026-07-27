"""Head-to-head records are derived solely from the match archive."""

import pytest

from arabfootball.derive import h2h
from arabfootball.store.db import Store


@pytest.fixture()
def store():
    database = Store(":memory:")
    yield database
    database.close()


def _team(store, name):
    return store.create_entity(type="team", name_en=name, country="SA")


def _match(store, match_id, home, away, kickoff, home_score, away_score, status="finished"):
    store.conn.execute(
        """
        INSERT INTO matches (
            id, home_entity, away_entity, kickoff_utc, status, home_score, away_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (match_id, home, away, kickoff, status, home_score, away_score),
    )
    store.conn.commit()


def test_h2h_returns_meetings_newest_first_and_summary_from_a_perspective(store):
    a, b = _team(store, "Al Hilal"), _team(store, "Al Nassr")
    _match(store, "old-win", a, b, "2023-01-01T18:00:00+00:00", 2, 0)
    _match(store, "draw", b, a, "2023-06-01T18:00:00+00:00", 1, 1)
    _match(store, "new-loss", b, a, "2024-01-01T18:00:00+00:00", 3, 1)

    result = h2h(store, a, b)

    assert [meeting["id"] for meeting in result["meetings"]] == [
        "new-loss",
        "draw",
        "old-win",
    ]
    assert result["summary"] == {"wins": 1, "draws": 1, "losses": 1}


def test_h2h_ignores_non_finished_fixtures_and_other_opponents(store):
    a, b, c = _team(store, "Al Hilal"), _team(store, "Al Nassr"), _team(store, "Al Ahli")
    _match(store, "finished", b, a, "2024-01-01T18:00:00+00:00", 0, 2)
    _match(store, "scheduled", a, b, "2025-01-01T18:00:00+00:00", None, None, "scheduled")
    _match(store, "other", a, c, "2024-06-01T18:00:00+00:00", 4, 0)

    result = h2h(store, a, b)

    assert [meeting["id"] for meeting in result["meetings"]] == ["finished"]
    assert result["summary"] == {"wins": 1, "draws": 0, "losses": 0}


def test_h2h_returns_empty_record_when_clubs_have_never_met(store):
    a, b = _team(store, "Al Hilal"), _team(store, "Al Nassr")

    assert h2h(store, a, b) == {
        "meetings": [],
        "summary": {"wins": 0, "draws": 0, "losses": 0},
    }
