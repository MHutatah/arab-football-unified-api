import json
from pathlib import Path

import httpx

from arabfootball.collectors.scores365 import Scores365Collector
from arabfootball.store.db import Store


def test_canned_games_are_paged_and_normalized_without_network():
    payload = json.loads(
        (Path(__file__).parent / "fixtures" / "365scores_games.json").read_text()
    )
    requests = []

    def handler(request):
        requests.append(request)
        # Return one repeated game to prove page boundaries cannot duplicate it.
        page = payload if len(requests) == 1 else {"games": [payload["games"][1]]}
        return httpx.Response(200, json=page)

    store = Store(":memory:")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = Scores365Collector(store, client=client, window_days=2).collect(
            season_start="2025-08-28", season_end="2025-09-01"
        )

    assert [dict(request.url.params) for request in requests] == [
        {"competitions": "649", "startDate": "2025-08-28", "endDate": "2025-08-29"},
        {"competitions": "649", "startDate": "2025-08-30", "endDate": "2025-08-31"},
        {"competitions": "649", "startDate": "2025-09-01", "endDate": "2025-09-01"},
    ]
    assert all(request.url.path == "/web/games/" for request in requests)
    assert records == [
        {
            "home_team": {"name": "Al Hilal", "provider_ids": {"365scores": "5457"}},
            "away_team": {"name": "Al Riyadh", "provider_ids": {"365scores": "5458"}},
            "kickoff_utc": "2025-08-28T18:00:00+00:00",
            "status": "finished",
            "home_score": 2,
            "away_score": 1,
            "provider_ids": {"365scores": "9001"},
            "competition_provider_ids": {"365scores": "649"},
        },
        {
            "home_team": {"name": "Al Ittihad", "provider_ids": {"365scores": "5460"}},
            "away_team": {"name": "Al Nassr", "provider_ids": {"365scores": "5461"}},
            "kickoff_utc": "2025-08-29T18:30:00+00:00",
            "status": "scheduled",
            "home_score": None,
            "away_score": None,
            "provider_ids": {"365scores": "9002"},
            "competition_provider_ids": {"365scores": "649"},
        },
    ]
    run = store.conn.execute("SELECT status FROM source_runs").fetchone()
    assert run["status"] == "ok"
    store.close()


def test_invalid_season_window_fails_soft():
    store = Store(":memory:")
    assert Scores365Collector(store).collect(
        season_start="2025-09-02", season_end="2025-09-01"
    ) == []
    run = store.conn.execute("SELECT status, errors FROM source_runs").fetchone()
    assert run["status"] == "failed"
    assert "season_end" in json.loads(run["errors"])[0]["message"]
    store.close()
