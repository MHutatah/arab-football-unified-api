"""Recent form is derived from stored matches, never a provider."""
import pytest

from arabfootball.derive import form
from arabfootball.store.db import Store


@pytest.fixture()
def store():
    store = Store(":memory:")
    teams = ("team:hilal", "team:nassr", "team:ahli")
    store.conn.executemany(
        """
        INSERT INTO entities (id, type, name_en, country, created_at)
        VALUES (?, 'team', ?, 'SA', '2025-01-01T00:00:00+00:00')
        """,
        ((team, team) for team in teams),
    )
    store.conn.executemany(
        """
        INSERT INTO matches (
            id, home_entity, away_entity, kickoff_utc, status, home_score, away_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("old-win", "team:hilal", "team:nassr", "2025-01-01T18:00:00Z",
             "finished", 2, 0),
            ("away-win", "team:nassr", "team:hilal", "2025-01-02T18:00:00Z",
             "finished", 1, 3),
            ("draw", "team:hilal", "team:ahli", "2025-01-03T18:00:00Z",
             "finished", 1, 1),
            ("away-loss", "team:ahli", "team:hilal", "2025-01-04T18:00:00Z",
             "finished", 2, 0),
            ("live", "team:hilal", "team:nassr", "2025-01-05T18:00:00Z",
             "live", 4, 0),
            ("scheduled", "team:hilal", "team:ahli", "2025-01-06T18:00:00Z",
             "scheduled", None, None),
        ],
    )
    store.conn.commit()
    yield store
    store.close()


def test_form_returns_last_n_finished_matches_most_recent_first(store):
    recent = form(store, "team:hilal", 3)

    assert [match["id"] for match in recent["matches"]] == [
        "away-loss", "draw", "away-win",
    ]
    assert recent["played"] == 3


def test_form_scores_home_and_away_results_from_requested_team_perspective(store):
    recent = store.form("team:hilal", 10)

    assert [(match["result"], match["points"]) for match in recent["matches"]] == [
        ("L", 0), ("D", 1), ("W", 3), ("W", 3),
    ]
    assert [(match["goals_for"], match["goals_against"]) for match in recent["matches"]] == [
        (0, 2), (1, 1), (3, 1), (2, 0),
    ]
    assert {
        key: recent[key] for key in ("wins", "draws", "losses", "points")
    } == {"wins": 2, "draws": 1, "losses": 1, "points": 7}


@pytest.mark.parametrize(("team", "n"), [("team:unknown", 5), ("team:hilal", 0)])
def test_form_returns_an_empty_summary_when_there_is_no_history(store, team, n):
    assert form(store, team, n) == {
        "team": team,
        "matches": [],
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "points": 0,
    }
