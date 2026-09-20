"""Name lookup over stored entities — the read side of resolution.

`resolve()` answers "which entity is this provider record?" and creates one when
nothing fits. Search answers a *human's* question — "الهلال", "hilal", "Al-Hilal
SFC" — and may only ever return what is already stored.

The ladder is the resolver's, relaxed for a person typing into a box: an exact
normalized hit, then the cross-script skeleton (so an Arabic query finds a club
stored under its English name and vice versa), then a substring of a stored
name, then bounded fuzzy for transliteration noise. Nothing is ever created, and
a query that matches nothing is an empty list, not a guess.
"""
from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

from arabfootball.resolve.normalize import norm, similarity, xkey

if TYPE_CHECKING:
    from arabfootball.store.db import Store

# Lower than the resolver's FUZZY_THRESHOLD: a wrong search hit costs a reader
# one glance, while a wrong resolution silently corrupts the archive.
SEARCH_THRESHOLD = 0.7

# Short keys collide across unrelated names, so skeleton and substring matching
# both need something long enough to mean anything.
MIN_PARTIAL = 3


def search(store: Store, q: str, *, type: str | None = None, country: str | None = None,
           limit: int = 20) -> list[dict]:
    """Stored entities matching ``q`` in either script, best match first.

    Each result is the entity row plus the ``score`` it matched at and the
    ``method`` that found it. ``type`` and ``country`` narrow the scope exactly
    as they do during resolution.
    """
    key = norm(q)
    if not key or limit <= 0:
        return []
    skeleton = _squeeze(xkey(q))

    variants: dict[str, list[str]] = {}
    for row in store.conn.execute("SELECT entity_id, name_variant FROM aliases"):
        variants.setdefault(row["entity_id"], []).append(row["name_variant"])

    sql = "SELECT * FROM entities"
    filters, args = [], []
    if type:
        filters.append("type=?")
        args.append(type)
    if country:
        filters.append("country=?")
        args.append(country.upper())
    if filters:
        sql += " WHERE " + " AND ".join(filters)

    hits = []
    for row in store.conn.execute(sql, args):
        entity = dict(row)
        names = [entity["name_ar"], entity["name_en"], *variants.get(entity["id"], ())]
        scored = _best(names, q, key, skeleton)
        if scored:
            score, method = scored
            hits.append({**entity, "score": score, "method": method})

    hits.sort(key=lambda h: (-h["score"], h["name_en"] or h["name_ar"] or "", h["id"]))
    return hits[:limit]


def _best(names, q: str, key: str, skeleton: str) -> tuple[float, str] | None:
    """The strongest way any of ``names`` matches the query, if any does."""
    best: tuple[float, str] | None = None
    for name in names:
        if not name:
            continue
        candidate = _match(name, q, key, skeleton)
        if candidate and (best is None or candidate[0] > best[0]):
            best = candidate
            if best[0] >= 1.0:
                break
    return best


def _squeeze(skeleton: str) -> str:
    """Collapse doubled consonants: a shadda is one Arabic letter and two Latin
    ones, so "الاتحاد" carries t-h-d where "Al-Ittihad" carries t-t-h-d."""
    return "".join(letter for letter, _ in itertools.groupby(skeleton))


def _match(name: str, q: str, key: str, skeleton: str) -> tuple[float, str] | None:
    normalized = norm(name)
    if not normalized:
        return None
    if normalized == key:
        return 1.0, "exact"
    if len(skeleton) >= MIN_PARTIAL and _squeeze(xkey(name)) == skeleton:
        return 0.9, "cross_script"
    if len(key) >= MIN_PARTIAL and len(normalized) >= MIN_PARTIAL and (
            key in normalized or normalized in key):
        return 0.8, "partial"
    score = similarity(name, q)
    return (score, "fuzzy") if score >= SEARCH_THRESHOLD else None
