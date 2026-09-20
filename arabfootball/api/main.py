"""The bundled read server — `make serve`.

Not a hosted service: a consumer runs this themselves against the snapshot they
downloaded. Every answer comes from the local store, so there is no key, no
rate limit and no upstream to go stale.

The response shape is bilingual by construction (see `lang.py`): both names are
always returned and `?lang=ar|en` chooses the `display_name`.
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from arabfootball.api.lang import entity_payload, parse_lang
from arabfootball.resolve.normalize import norm, xkey
from arabfootball.store.db import Store

DB_ENV = "ARABFOOTBALL_DB"
DEFAULT_DB = "arabfootball.db"

# A skeleton shorter than this collides across unrelated names (see `xkey`).
MIN_SKELETON = 3


def _names(store: Store, entity: dict) -> list[str]:
    """Every spelling we hold for an entity — its own names and its aliases."""
    names = [entity["name_ar"], entity["name_en"]]
    names += [row["name_variant"] for row in store.conn.execute(
        "SELECT name_variant FROM aliases WHERE entity_id=?", (entity["id"],))]
    return [n for n in names if n]


def search(store: Store, q: str, *, type: str | None = None,
           country: str | None = None, limit: int = 20) -> list[dict]:
    """Entities whose name matches `q` in either script, best match first."""
    key, skeleton = norm(q), xkey(q)
    if not key:
        return []

    sql = "SELECT * FROM entities WHERE 1=1"
    args: list[str] = []
    if type:
        sql += " AND type=?"
        args.append(type)
    if country:
        sql += " AND country=?"
        args.append(country)

    ranked: list[tuple[int, str, dict]] = []
    for row in store.conn.execute(sql, args):
        entity = dict(row)
        rank = 0
        for name in _names(store, entity):
            name_key = norm(name)
            if name_key == key:
                rank = max(rank, 3)
            elif name_key and key in name_key:
                rank = max(rank, 2)
            elif len(skeleton) >= MIN_SKELETON and xkey(name) == skeleton:
                rank = max(rank, 1)
        if rank:
            ranked.append((rank, entity["id"], entity))

    ranked.sort(key=lambda hit: (-hit[0], hit[1]))
    return [entity for _, _, entity in ranked[:limit]]


def get_store(request: Request) -> Store:
    """The store this app serves from — injected by the tests, else the snapshot."""
    if request.app.state.store is None:
        # A shared read connection: FastAPI answers these from a threadpool.
        request.app.state.store = Store(os.environ.get(DB_ENV, DEFAULT_DB),
                                        check_same_thread=False)
    return request.app.state.store


def lang_param(lang: str | None = Query(
        default=None, description="display language for `display_name`: ar|en")) -> str:
    """`?lang=` as a validated language code — Arabic when unspecified."""
    try:
        return parse_lang(lang)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


StoreDep = Annotated[Store, Depends(get_store)]
LangDep = Annotated[str, Depends(lang_param)]


def create_app(store: Store | None = None) -> FastAPI:
    """Build the app; `store` is injected by the tests, opened lazily otherwise."""
    app = FastAPI(
        title="Arab Football Unified API",
        version="0.1.0",
        description="Bilingual read API over a local snapshot. Names are returned in "
                    "both scripts; `?lang=ar|en` selects `display_name`.",
    )
    app.state.store = store

    @app.get("/v1/search")
    def search_entities(q: str, store: StoreDep, lang: LangDep,
                        type: str | None = None, country: str | None = None,
                        limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
        results = search(store, q, type=type, country=country, limit=limit)
        return {
            "query": q,
            "lang": lang,
            "count": len(results),
            "results": [entity_payload(entity, lang) for entity in results],
        }

    @app.get("/v1/teams/{entity_id}")
    def team(entity_id: str, store: StoreDep, lang: LangDep) -> dict:
        entity = store.entity(entity_id)
        if entity is None or entity["type"] != "team":
            raise HTTPException(status_code=404, detail=f"no team with id {entity_id!r}")
        return {**entity_payload(entity, lang), "lang": lang}

    return app


app = create_app()
