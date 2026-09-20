"""The bundled `/v1` read server — the snapshot, queryable over HTTP.

This is not a hosted service: a consumer runs it themselves against the SQLite
file they downloaded, with no keys and no configuration. Every answer comes from
the store alone — form and head-to-head are derived on the spot, never fetched —
so the server works offline and outlives any upstream feed.

Entities are always returned with both `name_ar` and `name_en`: names are labels
here, never keys, and the caller picks which one to display.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request

from arabfootball.derive import form as derive_form
from arabfootball.derive import h2h as derive_h2h
from arabfootball.resolve.search import search as search_entities
from arabfootball.store.db import Store

DEFAULT_DB = "arabfootball.db"
MATCH_PAGE_LIMIT = 100

router = APIRouter(prefix="/v1", tags=["v1"])


# ── wiring ──────────────────────────────────────────────────────────────────
def _store(request: Request) -> Iterator[Store]:
    """One SQLite connection per request — cheap, and safe across threadpools."""
    path = request.app.state.db_path
    if path != ":memory:" and not Path(path).exists():
        raise HTTPException(
            status_code=503,
            detail=f"no database at {path} — run `make pull-db` to fetch a snapshot")
    store = Store(path)
    try:
        yield store
    finally:
        store.close()


StoreDep = Annotated[Store, Depends(_store)]


def create_app(db_path: str | None = None) -> FastAPI:
    """Build the read API against ``db_path`` (env `ARABFOOTBALL_DB`, else CWD)."""
    app = FastAPI(
        title="Arab Football Unified API",
        version="0.1.0",
        description="Read-only queries over a local ODbL snapshot. Both names, always.")
    app.state.db_path = db_path or os.environ.get("ARABFOOTBALL_DB", DEFAULT_DB)
    app.include_router(router)
    return app


# ── serialization ───────────────────────────────────────────────────────────
def _entity(row: Mapping) -> dict:
    """An entity as the API returns it: both names, parsed meta, real boolean."""
    return {
        "id": row["id"],
        "type": row["type"],
        "name_ar": row["name_ar"],
        "name_en": row["name_en"],
        "country": row["country"],
        "provisional": bool(row["provisional"]),
        "meta": json.loads(row["meta"]) if row["meta"] else None,
    }


def _match(row: Mapping) -> dict:
    match = dict(row)
    match["provider_ids"] = json.loads(match["provider_ids"]) if match.get("provider_ids") else {}
    return match


# ── lookups ─────────────────────────────────────────────────────────────────
def _require(store: Store, entity_id: str, expected_type: str) -> dict:
    """Fetch an entity of ``expected_type``, or 404 saying exactly what's wrong."""
    entity = store.entity(entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail=_missing(store, entity_id, expected_type))
    if entity["type"] != expected_type:
        raise HTTPException(
            status_code=404,
            detail=f"unknown {expected_type}: {entity_id} is a {entity['type']}")
    return entity


def _missing(store: Store, entity_id: str, expected_type: str) -> str:
    """A merged-away id is not a typo — point the caller at what absorbed it."""
    row = store.conn.execute(
        "SELECT canonical_id FROM entity_merges WHERE provisional_id=?",
        (entity_id,)).fetchone()
    if row:
        return f"{entity_id} was merged into {row['canonical_id']}"
    return f"unknown {expected_type}: {entity_id}"


def _day(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}") from None


# ── endpoints ───────────────────────────────────────────────────────────────
@router.get("/search")
def search(
    store: StoreDep,
    q: Annotated[str, Query(min_length=1, description="a name in Arabic or English")],
    type: Annotated[str | None, Query(description="team|player|competition|manager|venue")] = None,
    country: Annotated[str | None, Query(description="ISO-3166 alpha-2, e.g. SA")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Resolve a name in either script to stored entities, best match first."""
    hits = search_entities(store, q, type=type, country=country, limit=limit)
    return {
        "query": q,
        "count": len(hits),
        "results": [
            {**_entity(hit), "score": round(hit["score"], 3), "method": hit["method"]}
            for hit in hits
        ],
    }


@router.get("/teams/{team_id}")
def team(
    store: StoreDep,
    team_id: str,
    form: Annotated[int, Query(ge=0, le=50, description="how many recent results")] = 5,
) -> dict:
    """A club profile with its form derived from the stored match archive."""
    entity = _require(store, team_id, "team")
    recent = derive_form(store, team_id, form)
    return {
        **_entity(entity),
        "form": {**recent, "matches": [_match(row) for row in recent["matches"]]},
    }


@router.get("/matches")
def matches(
    store: StoreDep,
    competition: Annotated[str | None, Query(description="competition entity id")] = None,
    from_: Annotated[str | None, Query(alias="from", description="ISO date, inclusive")] = None,
    to: Annotated[str | None, Query(description="ISO date, inclusive")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = MATCH_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Matches in kickoff order, filtered by competition and/or a date window."""
    if competition is not None:
        _require(store, competition, "competition")
    since, until = _day(from_, "from"), _day(to, "to")

    filters, args = [], []
    if competition:
        filters.append("competition_id=?")
        args.append(competition)
    # Compared on the calendar day: a window is stated in dates, while a stored
    # kickoff carries a time and a zone offset the caller never typed.
    if since:
        filters.append("substr(kickoff_utc,1,10)>=?")
        args.append(since)
    if until:
        filters.append("substr(kickoff_utc,1,10)<=?")
        args.append(until)

    sql = "SELECT * FROM matches"
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    sql += " ORDER BY kickoff_utc, id LIMIT ? OFFSET ?"
    rows = store.conn.execute(sql, (*args, limit, offset)).fetchall()
    return {
        "count": len(rows),
        "filters": {"competition": competition, "from": since, "to": until},
        "matches": [_match(row) for row in rows],
    }


@router.get("/h2h")
def h2h(
    store: StoreDep,
    a: Annotated[str, Query(description="team entity id")],
    b: Annotated[str, Query(description="the other team's entity id")],
) -> dict:
    """The head-to-head record between two clubs, derived from finished matches."""
    if a == b:
        raise HTTPException(status_code=400, detail=f"a and b are the same team: {a}")
    entity_a, entity_b = _require(store, a, "team"), _require(store, b, "team")
    record = derive_h2h(store, a, b)
    return {
        "a": _entity(entity_a),
        "b": _entity(entity_b),
        "meetings": [_match(row) for row in record["meetings"]],
        "summary": record["summary"],
    }


app = create_app()
