"""Raw collector records → resolved, forward-only rows in `matches`.

Nothing reaches the archive under a provider's own name or id: both clubs go
through the resolver first, so a match row is a statement about two canonical
entities. The store then applies the record forward-only — a feed that has gone
stale can add to a match, never subtract from it.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from arabfootball.resolve.normalize import script_of
from arabfootball.resolve.resolver import Resolver

NAME_KEYS = ("name", "name_ar", "name_en")

# Providers report more match states than the archive stores, and a real season
# produces every one of them. Each is collapsed onto the state the schema can
# actually represent; anything outside this table is a record we refuse rather
# than a state we invent. Postponed and cancelled games stay `scheduled` — they
# have not been played — while an abandoned one is over and will not resume.
STATUS_ALIASES = {
    "scheduled": "scheduled",
    "not_started": "scheduled",
    "postponed": "scheduled",
    "cancelled": "scheduled",
    "canceled": "scheduled",
    "live": "live",
    "in_play": "live",
    "half_time": "live",
    "suspended": "live",
    "finished": "finished",
    "ended": "finished",
    "full_time": "finished",
    "after_penalties": "finished",
    "abandoned": "finished",
    "awarded": "finished",
}


@dataclass
class IngestError:
    """One record the pass refused, kept so the drop is visible, never silent."""

    index: int
    reason: str


@dataclass
class IngestResult:
    """What one ingest pass did — an unchanged pass is the healthy resync."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    match_ids: list[str] = field(default_factory=list)
    errors: list[IngestError] = field(default_factory=list)


def ingest(store, records: Iterable[Mapping[str, Any]], *, country: str | None = None,
           resolver: Resolver | None = None, strict: bool = False) -> IngestResult:
    """Resolve and store normalized match records; returns what changed.

    `country` scopes identity resolution, which is what keeps a Saudi "Al Hilal"
    from meeting the Sudanese one.

    Each record is its own transaction and its own failure: one unusable row in a
    380-fixture season costs that row, not the 379 behind it, and whatever it had
    already written is rolled back rather than left orphaned. Refused records are
    listed on `result.errors`. `strict=True` re-raises instead, for callers that
    would rather hear about a malformed batch immediately.
    """
    resolver = resolver or Resolver(store)
    result = IngestResult()
    for index, record in enumerate(records):
        try:
            with store.atomic():
                match_id, outcome = _ingest_one(store, resolver, record, country)
        except Exception as exc:
            if strict:
                raise
            result.errors.append(IngestError(index=index, reason=str(exc)))
            continue
        if outcome == "inserted":
            result.inserted += 1
        elif outcome == "updated":
            result.updated += 1
        else:
            result.unchanged += 1
        result.match_ids.append(match_id)
    return result


def _ingest_one(store, resolver: Resolver, record: Mapping[str, Any],
                country: str | None) -> tuple[str, str]:
    status = _validate(record)

    # Both clubs resolve BEFORE the row exists: a match that cannot be attributed
    # to two entities is not storable at all.
    home = _resolve_team(store, resolver, record["home_team"], country)
    away = _resolve_team(store, resolver, record["away_team"], country)

    return store.upsert_match(
        home_entity=home,
        away_entity=away,
        kickoff_utc=record["kickoff_utc"],
        status=status,
        competition_id=_resolve_competition(store, resolver, record, country),
        season=record.get("season"),
        round=record.get("round"),
        home_score=record.get("home_score"),
        away_score=record.get("away_score"),
        provider_ids=record.get("provider_ids"),
    )


def _validate(record: Any) -> str:
    """Everything that can reject a record, checked before the first write.

    Resolving a club creates an entity and its aliases, so a record has to be
    known storable before it resolves anything — otherwise a row we go on to
    refuse has already put two provisional clubs in the review queue. Returns the
    record's status, collapsed onto the archive's ladder.
    """
    if not isinstance(record, Mapping):
        raise ValueError("ingest takes normalized record mappings")
    if not record.get("kickoff_utc"):
        raise ValueError("record has no kickoff_utc")
    for side in ("home_team", "away_team"):
        team = record.get(side)
        if not isinstance(team, Mapping):
            raise ValueError("record is missing a team")
        if not any(team.get(key) for key in NAME_KEYS):
            raise ValueError("record team has no name")
    return _status(record.get("status"))


def _status(value: Any) -> str:
    if not value:
        return "scheduled"
    key = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    if key not in STATUS_ALIASES:
        raise ValueError(f"unknown match status: {value!r}")
    return STATUS_ALIASES[key]


def _resolve_team(store, resolver: Resolver, team: Mapping[str, Any],
                  country: str | None) -> str:
    names = {key: team.get(key) for key in NAME_KEYS}
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

    The lookup is scoped to competitions: 365scores' league 649 and some club's
    id 649 are the same number, and an unscoped hit would quietly file a match
    under a team as its competition.
    """
    ids = _provider_ids(record.get("competition_provider_ids"))
    names = {key: record.get(f"competition_{key}") for key in NAME_KEYS}
    if not any(names.values()):
        for provider, provider_id in sorted(ids.items()):
            hit = store.find_by_provider(provider, provider_id, type="competition")
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
