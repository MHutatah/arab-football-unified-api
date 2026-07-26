import httpx
import pytest

from arabfootball.collectors.lineups import LineupCollector
from arabfootball.store.db import Store


@pytest.fixture()
def store():
    value = Store(":memory:")
    for entity_id, entity_type, name in (
        ("team:home", "team", "Home"),
        ("team:away", "team", "Away"),
    ):
        value.conn.execute(
            "INSERT INTO entities (id,type,name_en,provisional,created_at) VALUES (?,?,?,?,?)",
            (entity_id, entity_type, name, 0, "2025-01-01T00:00:00+00:00"),
        )
    value.conn.execute(
        """INSERT INTO matches
           (id, home_entity, away_entity, kickoff_utc, status)
           VALUES ('match:1', 'team:home', 'team:away', '2025-01-01T00:00:00Z', 'finished')"""
    )
    value.conn.commit()
    yield value
    value.close()


def test_lineup_members_become_idempotent_appearances_scoped_by_club(store):
    requests = []
    payloads = [
        {
            "game": {
                "homeCompetitor": {"id": 10},
                "awayCompetitor": {"id": 20},
                "members": [
                    {
                        "athleteId": 7,
                        "name": "Mohamed Ali",
                        "competitorId": 10,
                        "isStarter": True,
                        "minutesPlayed": 90,
                        "stats": {
                            "goals": 2,
                            "assists": 1,
                            "yellowCards": 1,
                            "redCards": 1,
                        },
                    },
                    {
                        # Deliberately the same provider id and name: player
                        # identity is club-scoped, not global.
                        "athleteId": 7,
                        "name": "Mohamed Ali",
                        "competitorId": 20,
                        "started": False,
                        "minutes": 25,
                        "goals": 1,
                        "redCards": 1,
                    },
                ],
            }
        },
        {
            "game": {
                "homeCompetitor": {"id": 10},
                "awayCompetitor": {"id": 20},
                "members": [
                    {
                        "athleteId": 7,
                        "name": "Mohamed Ali",
                        "competitorId": 10,
                    },
                    {
                        "athleteId": 7,
                        "name": "Mohamed Ali",
                        "competitorId": 20,
                    },
                ],
            }
        },
    ]

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payloads[len(requests) - 1])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        collector = LineupCollector(store, client=client)
        assert collector.collect(game_id=99, match_id="match:1") == 2
        assert collector.collect(game_id=99, match_id="match:1") == 2

    assert requests[0].url.path == "/web/game/"
    assert requests[0].url.params == {"gameId": "99", "withLineups": "true"}
    rows = store.conn.execute(
        "SELECT * FROM appearances ORDER BY team_entity"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["team_entity"] == "team:away"
    assert (rows[0]["started"], rows[0]["minutes"], rows[0]["goals"], rows[0]["red"]) == (
        0, 25, 1, 1,
    )
    assert rows[1]["team_entity"] == "team:home"
    assert (
        rows[1]["started"],
        rows[1]["minutes"],
        rows[1]["goals"],
        rows[1]["assists"],
        rows[1]["yellow"],
        rows[1]["red"],
    ) == (1, 90, 2, 1, 1, 1)
    assert rows[0]["player_entity"] != rows[1]["player_entity"]
    scopes = {
        row["provider"]
        for row in store.conn.execute("SELECT provider FROM aliases")
    }
    assert scopes == {"365scores:team:home", "365scores:team:away"}


def test_lineup_requires_an_existing_match(store):
    collector = LineupCollector(store)
    with pytest.raises(ValueError, match="unknown match"):
        collector.collect(game_id=99, match_id="missing")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, 1),
        (False, 0),
        (1, 1),
        (0, 0),
        ("true", 1),
        ("false", 0),
        ("1", 1),
        ("0", 0),
    ],
)
def test_started_parses_boolean_representations(value, expected):
    assert LineupCollector._started({"isStarter": value}) == expected
