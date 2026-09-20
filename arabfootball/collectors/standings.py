"""Seed a league's competition and club entities from its standings table.

Fixtures arrive before anything has told the store what the league *is*: the
first `/web/games/` ingest meets eighteen club names it has never seen and,
because the resolver never guesses, files every one of them as a provisional
entity for a human to confirm. Standings are the cheapest possible fix — one
request returns the league's complete club list carrying the provider's own
ids, so seeding it first makes the fixture ingest resolve at step 1 of the
ladder (provider id) instead of filling the review queue.

Seeded entities are canonical, not provisional: a club listed in its own
league's standings table is not a guess. The names already recorded for an
entity are kept, though — a maintainer's correction survives a reseed, and the
seed's own spelling is learned as an alias either way.

Nothing calls `seed_league` yet outside the tests. The entry point it belongs
in front of — `arabfootball.collectors.run`, which `make collect-saudi` already
invokes — is not in the repo yet and no sprint item creates it, so there is
nowhere to wire the ordering in. Whoever adds that module owns it: seed the
league, then ingest fixtures (the sprint's own `{K-08,K-11}→K-09` sequencing).
Until then a real run ingests unseeded and fills the review queue.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from arabfootball.collectors.base import Collector
from arabfootball.collectors.scores365 import SAUDI_PRO_LEAGUE_ID
from arabfootball.resolve.normalize import script_of
from arabfootball.resolve.resolver import Resolver

BASE_URL = "https://webws.365scores.com/web/standings/"
PROVIDER = "365scores"


@dataclass(frozen=True)
class LeagueSeed:
    """A league the store knows by name, independent of any feed's spelling."""

    provider_id: str
    name_en: str
    name_ar: str
    country: str
    also_known_as: tuple[str, ...] = ()


# The competition entity is curated rather than read off the feed: a fixtures
# response carries the league id but rarely a name, and never both of them.
SAUDI_PRO_LEAGUE = LeagueSeed(
    provider_id=SAUDI_PRO_LEAGUE_ID,
    name_en="Roshn Saudi League",
    name_ar="دوري روشن السعودي",
    country="SA",
    also_known_as=("Saudi Pro League", "الدوري السعودي للمحترفين"),
)


@dataclass
class SeedResult:
    """What one seeding pass did — a reseed of a seeded league changes nothing."""

    competition_id: str
    team_ids: list[str] = field(default_factory=list)
    created: int = 0
    promoted: int = 0      # entities that were provisional and are now canonical


class StandingsCollector(Collector):
    """Collect a competition's standings table as one record per club."""

    name = "365scores-standings"

    def __init__(self, store, *, client: httpx.Client | None = None, **kwargs: Any):
        super().__init__(store, **kwargs)
        self.client = client or httpx.Client(timeout=20)

    def _collect(
        self, *, competition_id: str | int = SAUDI_PRO_LEAGUE_ID
    ) -> list[dict[str, Any]]:
        response = self.client.get(
            BASE_URL, params={"competitions": str(competition_id)}
        )
        response.raise_for_status()
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in _rows(response.json()):
            record = self._normalize(row, competition_id)
            provider_id = record["provider_ids"][PROVIDER]
            if provider_id not in seen:
                seen.add(provider_id)
                records.append(record)
        # The table's own order, so a seed is deterministic and reads like the
        # league table a maintainer is looking at. A row the feed did not
        # position goes last — and `last` is computed BEFORE the sort, because
        # `list.sort` empties the list while it runs, which would otherwise
        # make the fallback 1 and float those rows to the top.
        last = len(records) + 1
        records.sort(key=lambda record: last if record["position"] is None
                     else record["position"])
        return records

    @staticmethod
    def _normalize(row: Any, competition_id: str | int) -> dict[str, Any]:
        if not isinstance(row, Mapping):
            raise ValueError("standings rows[] contains an invalid row")
        competitor = row.get("competitor")
        if not isinstance(competitor, Mapping):
            competitor = row
        provider_id = competitor.get("id", row.get("competitorId"))
        name = competitor.get("name") or row.get("competitorName")
        if provider_id is None or not name:
            raise ValueError("standings row has an invalid competitor")
        return {
            "name": str(name),
            "provider_ids": {PROVIDER: str(provider_id)},
            "position": _position(row),
            "competition_provider_ids": {PROVIDER: str(competition_id)},
        }


def seed_league(store, clubs: Iterable[Mapping[str, Any]], *,
                league: LeagueSeed = SAUDI_PRO_LEAGUE,
                resolver: Resolver | None = None) -> SeedResult:
    """Record the league and every club in its standings as canonical entities.

    Each club still goes through the resolver, so a provisional entity an
    earlier fixture ingest created is *promoted* rather than duplicated — the
    provider id it already carries is what finds it.
    """
    resolver = resolver or Resolver(store)
    competition_id, created, promoted = _seed(
        store, resolver, type="competition", provider_id=league.provider_id,
        names={"name_en": league.name_en, "name_ar": league.name_ar},
        country=league.country)
    # Spellings other feeds use for the same league, so their records resolve
    # by name even before they have taught us their own id for it.
    for name in league.also_known_as:
        store.add_alias(competition_id, "manual", None, name, script_of(name))

    result = SeedResult(competition_id=competition_id, created=created, promoted=promoted)
    for club in clubs:
        name, provider_id = _club(club)
        entity_id, created, promoted = _seed(
            store, resolver, type="team", provider_id=provider_id,
            names=_named(name), country=league.country)
        result.team_ids.append(entity_id)
        result.created += created
        result.promoted += promoted
    return result


# ── helpers ─────────────────────────────────────────────────────────────────
def _named(name: str) -> dict[str, str]:
    """A club's one spelling, under the name column its script belongs in.

    Both consumers of this take `name_ar`/`name_en` and nothing else, so the
    column is chosen from an explicit pair rather than by interpolating a
    script code into a keyword name: a future third script code would then be
    a `TypeError` deep inside the resolver instead of an Arabic name landing
    in `name_en`.
    """
    return {"name_ar" if script_of(name) == "ar" else "name_en": name}


def _seed(store, resolver: Resolver, *, type: str, provider_id: str,
          names: Mapping[str, str], country: str) -> tuple[str, int, int]:
    resolution = resolver.resolve(type=type, provider=PROVIDER,
                                  provider_id=provider_id, country=country, **names)
    existing = store.entity(resolution.entity_id) or {}
    store.confirm_entity(resolution.entity_id, country=country, **names)
    created = 1 if resolution.method == "created" else 0
    promoted = 1 if not created and existing.get("provisional") else 0
    return resolution.entity_id, created, promoted


def _club(club: Any) -> tuple[str, str]:
    if not isinstance(club, Mapping):
        raise ValueError("seed_league takes normalized club records")
    name = club.get("name")
    ids = club.get("provider_ids")
    provider_id = ids.get(PROVIDER) if isinstance(ids, Mapping) else None
    if not name or provider_id is None:
        # A club without the provider's id is unseedable: seeding exists to put
        # that id in `aliases`, and a name-only row would seed a club the next
        # fixture ingest still cannot resolve by id.
        raise ValueError("club record needs a name and a 365scores id")
    return str(name), str(provider_id)


def _rows(payload: Any) -> list[Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("standings response is not an object")
    standings = payload.get("standings")
    groups = standings if isinstance(standings, list) else [standings]
    rows: list[Any] = []
    for group in groups:
        if isinstance(group, Mapping) and isinstance(group.get("rows"), list):
            rows.extend(group["rows"])
    if not rows:
        raise ValueError("standings response has no rows[]")
    return rows


def _position(row: Mapping[str, Any]) -> int | None:
    for key in ("position", "rank"):
        try:
            return int(row[key])
        except (KeyError, TypeError, ValueError):
            continue
    return None
