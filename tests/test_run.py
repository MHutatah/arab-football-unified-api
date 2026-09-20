"""The producer run: seed first, ingest second, and measure what that bought."""
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from arabfootball.collectors import run as runner
from arabfootball.collectors.run import (
    LEAGUES,
    PROVISIONAL_RATE_KEY,
    format_run,
    main,
    run,
    season_window,
)
from arabfootball.collectors.scores365 import Scores365Collector
from arabfootball.collectors.standings import SAUDI_PRO_LEAGUE, StandingsCollector
from arabfootball.store.db import Store

FIXTURES = Path(__file__).parent / "fixtures"

# One window wide enough for both canned fixtures and narrow enough to be a
# single request, so the canned payload is not replayed as a second page.
SEASON = {"season_start": date(2025, 8, 28), "season_end": date(2025, 9, 1)}


@pytest.fixture()
def store():
    value = Store(":memory:")
    yield value
    value.close()


def canned(path, requests=None, status=200):
    payload = json.loads((FIXTURES / path).read_text())

    def handler(request):
        if requests is not None:
            requests.append(request)
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def run_saudi(store, *, requests=None, standings_status=200, **kwargs):
    """A whole run against canned 365Scores payloads, with no network."""
    with canned("365scores_standings.json", requests, standings_status) as table, \
            canned("365scores_games.json", requests) as games:
        return run(
            store,
            standings=StandingsCollector(store, client=table),
            fixtures=Scores365Collector(store, client=games, window_days=31),
            **{**SEASON, **kwargs},
        )


def recorded_rate(store):
    return json.loads(store.meta(PROVISIONAL_RATE_KEY))


def test_a_run_seeds_the_league_before_it_ingests_a_fixture(store):
    requests = []

    result = run_saudi(store, requests=requests)

    # Standings first, fixtures second — the whole point of the runner.
    assert [request.url.path for request in requests] == ["/web/standings/", "/web/games/"]
    assert dict(requests[0].url.params) == {"competitions": "649"}
    assert dict(requests[1].url.params) == {
        "competitions": "649", "startDate": "2025-08-28", "endDate": "2025-09-01"}

    assert result.clubs == 18
    assert result.seed.created == 19  # the competition and all eighteen clubs
    assert result.ingested.inserted == 2
    # Nothing was left for a human to confirm: every club resolved by id.
    assert store.review_queue() == []


def test_a_seeded_run_measures_and_records_a_zero_provisional_rate(store):
    result = run_saudi(store)

    assert (result.provisional.provisional, result.provisional.entities) == (0, 5)
    assert result.provisional.rate == 0.0
    assert result.provisional.matches == 2

    # Recorded, not just returned: the snapshot carries its own figure.
    stamped = recorded_rate(store)
    assert stamped["rate"] == 0.0
    assert stamped["entities"] == 5
    assert stamped["measured_at"].endswith("+00:00")


def test_the_same_run_without_the_seed_measures_a_full_provisional_rate(store):
    """`--no-seed` is the control: it is what makes the seeded 0 % mean anything."""
    result = run_saudi(store, seed=False)

    assert result.seed is None
    # Four clubs, no competition to attach at all, every one of them a guess
    # the resolver refused to make.
    assert (result.provisional.provisional, result.provisional.entities) == (4, 4)
    assert result.provisional.rate == 1.0
    assert recorded_rate(store)["rate"] == 1.0
    assert len(store.review_queue()) == 4


def test_a_second_run_re_measures_rather_than_appending(store):
    run_saudi(store, seed=False)
    assert recorded_rate(store)["rate"] == 1.0

    run_saudi(store)

    # The seed promoted the provisionals the first run left behind, and the
    # stamp says so — one key, always the latest measurement.
    assert recorded_rate(store)["rate"] == 0.0
    assert store.conn.execute(
        "SELECT COUNT(*) c FROM snapshot_meta").fetchone()["c"] == 1


def test_seeding_only_stops_before_any_fixture(store):
    result = run_saudi(store, ingest_fixtures=False)

    assert result.seed.created == 19
    assert result.ingested is None
    # Nothing was ingested, so there is no rate to measure and none is stamped.
    assert result.provisional is None
    assert store.meta(PROVISIONAL_RATE_KEY) is None
    assert store.conn.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"] == 0


def test_a_run_that_neither_seeds_nor_ingests_is_refused(store):
    with pytest.raises(ValueError, match="seed, ingest, or both"):
        run(store, seed=False, ingest_fixtures=False)


def test_a_failed_standings_fetch_still_seeds_the_competition_and_ingests(store):
    """Fail-soft: one source down must not stop the run (NFR-failsoft)."""
    result = run_saudi(store, standings_status=500)

    assert result.clubs == 0
    assert result.seed.created == 1  # the curated competition, read off no feed
    assert store.entity(result.seed.competition_id)["name_ar"] == SAUDI_PRO_LEAGUE.name_ar
    # The fixtures still landed, and the measurement records the cost of the
    # clubs that could not be seeded rather than hiding it.
    assert result.ingested.inserted == 2
    assert (result.provisional.provisional, result.provisional.entities) == (4, 5)
    assert store.conn.execute(
        "SELECT status FROM source_runs WHERE collector='365scores-standings'"
    ).fetchone()["status"] == "failed"


def test_an_ingest_that_attributed_nothing_measures_no_rate_at_all(store):
    """A fixtures feed that is down measures nothing — never a perfect score.

    Seen on the first real run: `/web/games/` answered without a `games[]`, the
    collector failed soft, and a rate of 0 would have stamped the snapshot with
    a flawless figure earned by ingesting nothing.
    """
    with canned("365scores_standings.json") as table, \
            canned("365scores_games.json", status=503) as games:
        result = run(store,
                     standings=StandingsCollector(store, client=table),
                     fixtures=Scores365Collector(store, client=games, window_days=31),
                     **SEASON)

    assert (result.provisional.matches, result.provisional.entities) == (0, 0)
    assert result.provisional.rate is None
    assert recorded_rate(store)["rate"] is None
    assert "not measured" in format_run(result)


def test_the_season_window_defaults_to_the_season_the_day_belongs_to(store):
    assert season_window(date(2026, 9, 20)) == (date(2026, 8, 1), date(2027, 6, 30))
    # February is the back half of the season that started the previous August.
    assert season_window(date(2026, 2, 14)) == (date(2025, 8, 1), date(2026, 6, 30))
    # July, the gap between seasons, belongs to the one about to start.
    assert season_window(date(2026, 7, 1)) == (date(2026, 8, 1), date(2027, 6, 30))


def test_a_run_with_no_window_given_fetches_the_current_season(store):
    result = run_saudi(store, season_start=None, season_end=None,
                       today=date(2026, 2, 14))

    assert (result.season_start, result.season_end) == (date(2025, 8, 1), date(2026, 6, 30))


# ── CLI ─────────────────────────────────────────────────────────────────────
def test_the_cli_runs_the_named_league_against_the_given_db(tmp_path, monkeypatch, capsys):
    calls = {}

    def fake_run(store, **kwargs):
        # `run` here is this module's own import, not the patched attribute.
        calls.update(kwargs)
        return run(store, standings=_down(StandingsCollector, store),
                   fixtures=_down(Scores365Collector, store), **kwargs)

    monkeypatch.setattr(runner, "run", fake_run)
    db = tmp_path / "arabfootball.db"

    assert main(["--competition", "saudi", "--db", str(db),
                 "--season-start", "2025-08-28", "--season-end", "2025-09-01"]) == 0

    assert calls["league"] is LEAGUES["saudi"]
    assert (calls["season_start"], calls["season_end"]) == (
        date(2025, 8, 28), date(2025, 9, 1))
    assert (calls["seed"], calls["ingest_fixtures"]) == (True, True)
    assert db.exists()
    assert "Roshn Saudi League" in capsys.readouterr().out


def test_the_cli_seed_only_flag_ingests_nothing(tmp_path, monkeypatch):
    calls = {}
    monkeypatch.setattr(runner, "run", lambda store, **kwargs: calls.update(kwargs))
    monkeypatch.setattr(runner, "format_run", lambda *a, **k: "")

    assert main(["--db", str(tmp_path / "db.sqlite"), "--seed-only"]) == 0

    assert (calls["seed"], calls["ingest_fixtures"]) == (True, False)


def test_the_cli_refuses_a_run_that_would_do_nothing(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        main(["--db", str(tmp_path / "db.sqlite"), "--seed-only", "--no-seed"])

    assert exit_info.value.code == 2


def test_the_cli_refuses_a_league_it_cannot_seed(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        main(["--db", str(tmp_path / "db.sqlite"), "--competition", "egypt"])

    assert exit_info.value.code == 2


def test_the_summary_reports_the_seed_the_ingest_and_the_rate(store):
    printed = format_run(run_saudi(store), review_queue=0)

    assert "Roshn Saudi League" in printed
    assert "seeded: competition + 18 club(s)" in printed
    assert "ingested 2025-08-28 → 2025-09-01: 2 inserted" in printed
    assert "provisional rate: 0.0% (0 of 5 entities)" in printed
    assert f"snapshot_meta.{PROVISIONAL_RATE_KEY}" in printed
    assert "await review" not in printed


def test_the_summary_points_an_unseeded_run_at_the_review_queue(store):
    result = run_saudi(store, seed=False)

    printed = format_run(result, review_queue=len(store.review_queue()))

    assert "provisional rate: 100.0% (4 of 4 entities)" in printed
    assert "4 entities await review: run `make review`" in printed


def test_the_summary_says_when_the_standings_collected_nothing(store):
    printed = format_run(run_saudi(store, standings_status=500))

    assert "seeded: competition + 0 club(s)" in printed
    assert "standings collected no clubs" in printed


def _down(collector, store):
    """A collector whose source is down — the CLI path, with nothing to fetch."""
    return collector(store, client=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))))
