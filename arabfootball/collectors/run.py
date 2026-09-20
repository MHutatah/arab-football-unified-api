"""The producer run — seed the league, then ingest its fixtures.

    make seed-saudi      # the league and its clubs, from /web/standings/
    make collect-saudi   # seed, then ingest the season's fixtures

The order is the story: a fixtures ingest that runs first meets eighteen club
names nothing has told the store about and, because the resolver never guesses,
files every one of them as a provisional entity for a human to confirm. Seeding
from the standings table puts the provider's own ids in `aliases` first, so the
same ingest resolves at step 1 of the ladder instead of filling the review
queue — the sprint's `{K-08,K-11}→K-09` sequencing, executed.

What that is worth is measured rather than asserted: `provisional_rate` counts
the entities the ingested matches point at, divides out the ones the resolver
refused to attribute, and stamps the figure into `snapshot_meta`, so a snapshot
carries its own identity-quality number instead of leaving a consumer to guess.
`--no-seed` measures the same run without the seed, which is what makes the
seeded figure mean anything.

Every step is fail-soft, because the collectors are: a standings fetch that
fails collects nothing, and the run still seeds the curated competition and
ingests what fixtures it can, reporting the clubs it could not seed.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

from arabfootball.collectors.ingest import IngestResult, ingest
from arabfootball.collectors.scores365 import Scores365Collector
from arabfootball.collectors.standings import (
    SAUDI_PRO_LEAGUE,
    LeagueSeed,
    SeedResult,
    StandingsCollector,
    seed_league,
)

# `snapshot_meta` key the latest provisional-rate measurement is stamped under.
PROVISIONAL_RATE_KEY = "provisional_rate"

# The entity columns an ingested match points at; each one is a resolution that
# either found a real entity or fell back to a provisional.
MATCH_ENTITY_COLUMNS = ("home_entity", "away_entity", "competition_id")

# Leagues this runner knows how to seed, by the name `--competition` takes.
LEAGUES: dict[str, LeagueSeed] = {"saudi": SAUDI_PRO_LEAGUE}


@dataclass
class ProvisionalRate:
    """How much of an ingest the resolver refused to attribute to a real entity.

    `rate` is `None`, never 0, when the ingest attributed no entities at all:
    a source that was down measures nothing, and a snapshot must not carry a
    perfect score earned by ingesting nothing.
    """

    matches: int
    entities: int
    provisional: int
    rate: float | None
    measured_at: str


@dataclass
class RunResult:
    """What one producer run did, in the order it did it."""

    league: LeagueSeed
    season_start: date
    season_end: date
    seed: SeedResult | None = None
    clubs: int = 0
    ingested: IngestResult | None = None
    provisional: ProvisionalRate | None = None


def season_window(today: date) -> tuple[date, date]:
    """The season containing `today`, as the date window the fixtures feed takes.

    Arab league seasons straddle the new year — August to June — so the season
    a date belongs to is decided by its month, not its year. July, the gap
    between them, belongs to the season about to start.
    """
    start_year = today.year if today.month >= 7 else today.year - 1
    return date(start_year, 8, 1), date(start_year + 1, 6, 30)


def run(store, *, league: LeagueSeed = SAUDI_PRO_LEAGUE,
        season_start: date | None = None, season_end: date | None = None,
        standings: StandingsCollector | None = None,
        fixtures: Scores365Collector | None = None,
        seed: bool = True, ingest_fixtures: bool = True,
        today: date | None = None) -> RunResult:
    """Seed `league` from its standings, ingest its season, measure the result.

    The collectors are injectable so the suite can drive a whole run against
    canned payloads; a real run builds them against the live endpoints.
    """
    if not (seed or ingest_fixtures):
        raise ValueError("a run must seed, ingest, or both")
    window = season_window(today or date.today())
    start = season_start or window[0]
    end = season_end or window[1]
    result = RunResult(league=league, season_start=start, season_end=end)

    if seed:
        collector = standings or StandingsCollector(store)
        clubs = collector.collect(competition_id=league.provider_id)
        # A standings fetch that failed collected nothing, and the competition
        # entity is curated rather than read off that feed — so seeding it is
        # still both correct and worth doing, and the clubs count says plainly
        # how much of the seed actually landed.
        result.clubs = len(clubs)
        result.seed = seed_league(store, clubs, league=league)

    if ingest_fixtures:
        collector = fixtures or Scores365Collector(store)
        records = collector.collect(season_start=start, season_end=end,
                                    competition_id=league.provider_id)
        result.ingested = ingest(store, records, country=league.country)
        result.provisional = provisional_rate(store, result.ingested)
    return result


def provisional_rate(store, result: IngestResult | Iterable[str], *,
                     key: str | None = PROVISIONAL_RATE_KEY) -> ProvisionalRate:
    """Measure the share of an ingest's entities that are provisional, and record it.

    This is the number that says whether seeding worked: ingesting a seeded
    league attributes every club to a canonical entity and measures 0, while an
    unseeded one measures 1 and puts the whole league in the review queue. The
    measurement is stamped into `snapshot_meta` under `key`, so the figure
    outlives the run that produced it; pass `key=None` to measure without
    recording.
    """
    match_ids = result.match_ids if isinstance(result, IngestResult) else list(result)
    entity_ids: set[str] = set()
    for match_id in match_ids:
        row = store.match(match_id)
        if row is None:
            continue
        entity_ids.update(row[column] for column in MATCH_ENTITY_COLUMNS if row[column])
    provisional = sum(
        1 for entity_id in entity_ids if (store.entity(entity_id) or {}).get("provisional"))
    measurement = ProvisionalRate(
        matches=len(match_ids),
        entities=len(entity_ids),
        provisional=provisional,
        rate=provisional / len(entity_ids) if entity_ids else None,
        measured_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    if key:
        store.set_meta(key, json.dumps(asdict(measurement), ensure_ascii=False))
    return measurement


# ── CLI ─────────────────────────────────────────────────────────────────────
def format_run(result: RunResult, *, review_queue: int | None = None) -> str:
    lines = [f"{result.league.name_en} / {result.league.name_ar}"
             f" ({result.league.country})"]
    if result.seed is not None:
        lines.append(f"  seeded: competition + {result.clubs} club(s)"
                     f" — {result.seed.created} created,"
                     f" {result.seed.promoted} promoted from provisional")
        if not result.clubs:
            lines.append("  ! standings collected no clubs — see source_runs;"
                         " the fixtures below resolve unseeded")
    if result.ingested is not None:
        lines.append(f"  ingested {result.season_start} → {result.season_end}:"
                     f" {result.ingested.inserted} inserted,"
                     f" {result.ingested.updated} updated,"
                     f" {result.ingested.unchanged} unchanged")
    if result.provisional is not None:
        rate = result.provisional
        measured = ("not measured — the ingest attributed no entities"
                    " (see source_runs)" if rate.rate is None
                    else f"{rate.rate:.1%} ({rate.provisional} of"
                         f" {rate.entities} entities)")
        lines.append(f"  provisional rate: {measured};"
                     f" recorded in snapshot_meta.{PROVISIONAL_RATE_KEY}")
    if review_queue:
        lines.append(f"  {review_queue} entit"
                     f"{'y' if review_queue == 1 else 'ies'} await review:"
                     " run `make review`")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m arabfootball.collectors.run",
        description="Seed a league from its standings table, then ingest its season.")
    parser.add_argument("--competition", default="saudi", choices=sorted(LEAGUES),
                        help="which league to run (default: saudi)")
    parser.add_argument("--db", default="arabfootball.db", help="path to the store")
    parser.add_argument("--season-start", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="first day to fetch (default: the current season)")
    parser.add_argument("--season-end", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="last day to fetch (default: the current season)")
    parser.add_argument("--seed-only", action="store_true",
                        help="seed the league and stop, ingesting no fixtures")
    parser.add_argument("--no-seed", dest="seed", action="store_false",
                        help="ingest without seeding — measures what the seed is worth")
    args = parser.parse_args(argv)
    if args.seed_only and not args.seed:
        parser.error("--seed-only and --no-seed leave nothing to do")

    from arabfootball.store.db import Store

    store = Store(args.db)
    try:
        result = run(store, league=LEAGUES[args.competition],
                     season_start=args.season_start, season_end=args.season_end,
                     seed=args.seed, ingest_fixtures=not args.seed_only)
        print(format_run(result, review_queue=len(store.review_queue())))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
