"""Raw collector records → resolved, forward-only rows in `matches`.

Nothing reaches the archive under a provider's own name or id: both clubs go
through the resolver first, so a match row is a statement about two canonical
entities. The store then applies the record forward-only — a feed that has gone
stale can add to a match, never subtract from it.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from arabfootball.resolve.normalize import script_of
from arabfootball.resolve.resolver import Resolver

NAME_KEYS = ("name", "name_ar", "name_en")

# `snapshot_meta` key the latest provisional-rate measurement is stamped under.
PROVISIONAL_RATE_KEY = "provisional_rate"

# The entity columns an ingested match points at; each one is a resolution that
# either found a real entity or fell back to a provisional.
MATCH_ENTITY_COLUMNS = ("home_entity", "away_entity", "competition_id")


@dataclass
class IngestResult:
    """What one ingest pass did — an unchanged pass is the healthy resync."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    match_ids: list[str] = field(default_factory=list)


def ingest(store, records: Iterable[Mapping[str, Any]], *, country: str | None = None,
           resolver: Resolver | None = None) -> IngestResult:
    """Resolve and store normalized match records; returns what changed.

    `country` scopes identity resolution, which is what keeps a Saudi "Al Hilal"
    from meeting the Sudanese one.
    """
    resolver = resolver or Resolver(store)
    result = IngestResult()
    for record in records:
        match_id, outcome = _ingest_one(store, resolver, record, country)
        if outcome == "inserted":
            result.inserted += 1
        elif outcome == "updated":
            result.updated += 1
        else:
            result.unchanged += 1
        result.match_ids.append(match_id)
    return result


@dataclass
class ProvisionalRate:
    """How much of an ingest the resolver refused to attribute to a real entity."""

    matches: int
    entities: int
    provisional: int
    rate: float
    measured_at: str


def provisional_rate(store, result: IngestResult | Iterable[str], *,
                     key: str | None = PROVISIONAL_RATE_KEY) -> ProvisionalRate:
    """Measure the share of an ingest's entities that are provisional, and record it.

    This is the number that says whether seeding worked: ingesting a seeded
    league should attribute every club to a canonical entity and measure 0,
    while an unseeded one measures 1 and puts the whole league in the review
    queue. The measurement is stamped into `snapshot_meta`, so a snapshot
    carries its own identity-quality figure rather than leaving a consumer to
    guess at it.
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
        rate=provisional / len(entity_ids) if entity_ids else 0.0,
        measured_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    if key:
        store.set_meta(key, json.dumps(asdict(measurement), ensure_ascii=False))
    return measurement


def _ingest_one(store, resolver: Resolver, record: Mapping[str, Any],
                country: str | None) -> tuple[str, str]:
    if not isinstance(record, Mapping):
        raise ValueError("ingest takes normalized record mappings")
    kickoff = record.get("kickoff_utc")
    if not kickoff:
        raise ValueError("record has no kickoff_utc")

    # Both clubs resolve BEFORE the row exists: a match that cannot be attributed
    # to two entities is not storable at all.
    home = _resolve_team(store, resolver, record.get("home_team"), country)
    away = _resolve_team(store, resolver, record.get("away_team"), country)

    return store.upsert_match(
        home_entity=home,
        away_entity=away,
        kickoff_utc=kickoff,
        status=record.get("status") or "scheduled",
        competition_id=_resolve_competition(store, resolver, record, country),
        season=record.get("season"),
        round=record.get("round"),
        home_score=record.get("home_score"),
        away_score=record.get("away_score"),
        provider_ids=record.get("provider_ids"),
    )


def _resolve_team(store, resolver: Resolver, team: Any, country: str | None) -> str:
    if not isinstance(team, Mapping):
        raise ValueError("record is missing a team")
    names = {key: team.get(key) for key in NAME_KEYS}
    if not any(names.values()):
        raise ValueError("record team has no name")
    ids = _provider_ids(team.get("provider_ids"))
    provider, provider_id = _primary(ids)
    resolution = resolver.resolve(
        type="team", provider=provider, provider_id=provider_id,
        country=team.get("country") or country, **names)
    _learn_remaining(store, resolution.entity_id, ids, provider, names)
    return resolution.entity_id


def _resolve_competition(store, resolver: Resolver, record: Mapping[str, Any],
                         country: str | None) -> str | None:
    """The competition an already-known id points at, or a resolved named one.

    A fixtures feed carries the competition id it was queried with but rarely a
    name; creating a nameless provisional entity for it would put an unreviewable
    row in the queue, so an unknown id without a name simply leaves the match
    unattached until the competition is seeded.
    """
    ids = _provider_ids(record.get("competition_provider_ids"))
    names = {key: record.get(f"competition_{key}") for key in NAME_KEYS}
    if not any(names.values()):
        for provider, provider_id in sorted(ids.items()):
            hit = store.find_by_provider(provider, provider_id)
            if hit:
                return hit
        return None
    provider, provider_id = _primary(ids)
    resolution = resolver.resolve(
        type="competition", provider=provider, provider_id=provider_id,
        country=country, **names)
    _learn_remaining(store, resolution.entity_id, ids, provider, names)
    return resolution.entity_id


def _provider_ids(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {str(provider): str(pid) for provider, pid in value.items() if pid is not None}


def _primary(ids: Mapping[str, str]) -> tuple[str, str | None]:
    """One provider drives resolution; the rest are learned as aliases."""
    for provider, provider_id in sorted(ids.items()):
        return provider, provider_id
    return "ingest", None


def _learn_remaining(store, entity_id: str, ids: Mapping[str, str], primary: str,
                     names: Mapping[str, str | None]) -> None:
    for provider, provider_id in sorted(ids.items()):
        if provider == primary:
            continue
        for name in filter(None, names.values()):
            store.add_alias(entity_id, provider, provider_id, name, script_of(name))
