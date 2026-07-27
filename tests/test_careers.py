"""Squads and careers are derived from appearances."""

import pytest

from arabfootball.derive import career, squad
from arabfootball.store.db import Store


@pytest.fixture()
def store():
    database = Store(":memory:")
    database.conn.executemany(
        """
        INSERT INTO entities (id, type, name_en, created_at)
        VALUES (?, ?, ?, '2025-01-01T00:00:00+00:00')
        """,
        [
            ("team:a", "team", "Club A"),
            ("team:b", "team", "Club B"),
            ("player:one", "player", "One"),
            ("player:two", "player", "Two"),
        ],
    )
    yield database
    database.close()


def _appearance(store, match_id, date, season, team, player, goals=0):
    opponent = "team:b" if team == "team:a" else "team:a"
    store.conn.execute(
        """
        INSERT INTO matches (id, season, home_entity, away_entity, kickoff_utc, status)
        VALUES (?, ?, ?, ?, ?, 'finished')
        """,
        (match_id, season, team, opponent, date),
    )
    store.conn.execute(
        """
        INSERT INTO appearances (player_entity, match_id, team_entity, goals)
        VALUES (?, ?, ?, ?)
        """,
        (player, match_id, team, goals),
    )
    store.conn.commit()


def test_squad_lists_players_and_counts_only_requested_team_and_season(store):
    _appearance(store, "m1", "2024-01-01T18:00:00Z", "2023-24", "team:a", "player:one")
    _appearance(store, "m2", "2024-01-02T18:00:00Z", "2023-24", "team:a", "player:one")
    _appearance(store, "m3", "2024-01-03T18:00:00Z", "2023-24", "team:a", "player:two")
    _appearance(store, "m4", "2025-01-01T18:00:00Z", "2024-25", "team:a", "player:two")
    _appearance(store, "m5", "2024-02-01T18:00:00Z", "2023-24", "team:b", "player:two")

    assert store.squad("team:a", "2023-24") == [
        {"player": "player:one", "name_ar": None, "name_en": "One", "appearances": 2},
        {"player": "player:two", "name_ar": None, "name_en": "Two", "appearances": 1},
    ]
    assert squad(store, "team:a", "missing") == []


def test_career_returns_ordered_appearance_runs_with_totals(store):
    _appearance(store, "m1", "2020-01-01T18:00:00Z", "2019-20", "team:a", "player:one", 1)
    _appearance(store, "m2", "2020-02-01T18:00:00Z", "2019-20", "team:a", "player:one", 2)
    _appearance(store, "m3", "2021-01-01T18:00:00Z", "2020-21", "team:b", "player:one", 3)
    _appearance(store, "m4", "2022-01-01T18:00:00Z", "2021-22", "team:a", "player:one", 4)

    assert career(store, "player:one") == [
        {
            "club": "team:a",
            "first_appearance": "2020-01-01T18:00:00Z",
            "last_appearance": "2020-02-01T18:00:00Z",
            "apps": 2,
            "goals": 3,
        },
        {
            "club": "team:b",
            "first_appearance": "2021-01-01T18:00:00Z",
            "last_appearance": "2021-01-01T18:00:00Z",
            "apps": 1,
            "goals": 3,
        },
        {
            "club": "team:a",
            "first_appearance": "2022-01-01T18:00:00Z",
            "last_appearance": "2022-01-01T18:00:00Z",
            "apps": 1,
            "goals": 4,
        },
    ]


def test_transfer_splits_same_club_appearances_without_inventing_appearances(store):
    _appearance(store, "m1", "2020-01-01T18:00:00Z", "2019-20", "team:a", "player:one")
    _appearance(store, "m2", "2022-01-01T18:00:00Z", "2021-22", "team:a", "player:one")
    store.conn.executemany(
        """
        INSERT INTO transfers (id, player_entity, from_entity, to_entity, date)
        VALUES (?, 'player:one', ?, ?, ?)
        """,
        [
            ("out", "team:a", "team:b", "2020-06-01"),
            ("back", "team:b", "team:a", "2021-06-01"),
        ],
    )
    store.conn.commit()

    result = store.career("player:one")

    assert [stint["club"] for stint in result] == ["team:a", "team:a"]
    assert [stint["apps"] for stint in result] == [1, 1]
    assert career(store, "player:unknown") == []
