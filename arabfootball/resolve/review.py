"""Review queue — list what the resolver refused to guess at, and merge it.

The resolver never guesses: an unresolvable record becomes a *provisional*
entity instead of a confident wrong match.  That safety only pays off if a
maintainer can clear the queue cheaply, so the correction is a one-liner:

    make review                                   # what needs a decision
    make merge FROM=team:ab12… INTO=team:cd34…    # this is that club

A merge repoints everything that referenced the provisional entity onto the
canonical one, keeps the misresolved spelling as an alias — so the next ingest
resolves it exactly, at step 1 of the ladder — and deletes the provisional.
Every merge is written to `entity_merges`, which makes a repeat of the same
merge a logged no-op rather than an error.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from arabfootball.resolve.normalize import script_of

if TYPE_CHECKING:
    from arabfootball.store.db import Store

# Every column that carries an entity id, except `aliases.entity_id` (repointed
# separately, because its rows have to be de-duplicated first). A merge repoints
# all of them: a leftover reference would both break the foreign key on delete
# and orphan real history from the club it belongs to.
ENTITY_REFERENCES: tuple[tuple[str, str], ...] = (
    ("matches", "competition_id"),
    ("matches", "home_entity"),
    ("matches", "away_entity"),
    ("matches", "venue_id"),
    ("appearances", "player_entity"),
    ("appearances", "team_entity"),
    ("team_seasons", "team_entity"),
    ("team_seasons", "competition_id"),
    ("transfers", "player_entity"),
    ("transfers", "from_entity"),
    ("transfers", "to_entity"),
    ("honours", "entity_id"),
    ("honours", "competition_id"),
    ("facts", "subject_entity"),
    # An entity that already absorbed others carries their audit trail with it.
    ("entity_merges", "canonical_id"),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class MergeError(Exception):
    """A merge that would corrupt identity rather than correct it."""


@dataclass
class MergeResult:
    provisional_id: str
    canonical_id: str
    aliases_moved: int
    already_merged: bool = False


def queue(store: Store) -> list[dict]:
    """Provisional entities, oldest first, each with its aliases and sources."""
    entries = []
    for entity in store.review_queue():
        entity["aliases"] = [
            dict(row)
            for row in store.conn.execute(
                "SELECT provider, provider_id, name_variant, script FROM aliases"
                " WHERE entity_id=? ORDER BY provider, name_variant",
                (entity["id"],),
            )
        ]
        entity["sources"] = sorted({a["provider"] for a in entity["aliases"]})
        entries.append(entity)
    return entries


def merge(store: Store, provisional_id: str, canonical_id: str) -> MergeResult:
    """Fold ``provisional_id`` into ``canonical_id``; safe to repeat verbatim."""
    canonical_id = _follow_merges(store, canonical_id)
    if provisional_id == canonical_id:
        raise MergeError(f"cannot merge {provisional_id} into itself")

    canonical = store.entity(canonical_id)
    if canonical is None:
        raise MergeError(f"unknown canonical entity: {canonical_id}")

    provisional = store.entity(provisional_id)
    if provisional is None:
        return _already_merged(store, provisional_id, canonical_id)
    if provisional["type"] != canonical["type"]:
        raise MergeError(
            f"type mismatch: {provisional_id} is a {provisional['type']},"
            f" {canonical_id} is a {canonical['type']}"
        )

    with store.conn:
        # Aliases the canonical entity already carries would violate the alias
        # uniqueness constraint (and say nothing new), so drop them first.
        store.conn.execute(
            """
            DELETE FROM aliases
            WHERE entity_id = ?
              AND EXISTS (
                SELECT 1 FROM aliases kept
                WHERE kept.entity_id = ?
                  AND kept.provider = aliases.provider
                  AND IFNULL(kept.provider_id, '') = IFNULL(aliases.provider_id, '')
                  AND kept.name_variant = aliases.name_variant
              )
            """,
            (provisional_id, canonical_id),
        )
        moved = store.conn.execute(
            "UPDATE aliases SET entity_id=? WHERE entity_id=?",
            (canonical_id, provisional_id),
        ).rowcount
        for table, column in ENTITY_REFERENCES:
            store.conn.execute(
                f"UPDATE {table} SET {column}=? WHERE {column}=?",
                (canonical_id, provisional_id),
            )

        # The spelling that failed to resolve is the whole point of the merge:
        # recorded as an alias, the next ingest of it matches exactly.
        for name in (provisional["name_ar"], provisional["name_en"]):
            moved += _record_spelling(store, canonical_id, name)

        store.conn.execute("DELETE FROM entities WHERE id=?", (provisional_id,))
        store.conn.execute(
            "INSERT INTO entity_merges"
            " (provisional_id, canonical_id, name_ar, name_en, aliases_moved, merged_at)"
            " VALUES (?,?,?,?,?,?)",
            (provisional_id, canonical_id, provisional["name_ar"],
             provisional["name_en"], moved, _now()),
        )
    return MergeResult(provisional_id, canonical_id, moved)


# ── helpers ─────────────────────────────────────────────────────────────────
def _follow_merges(store: Store, entity_id: str) -> str:
    """Resolve an id that was itself merged away to the entity that absorbed it."""
    seen = {entity_id}
    while store.entity(entity_id) is None:
        row = store.conn.execute(
            "SELECT canonical_id FROM entity_merges WHERE provisional_id=?",
            (entity_id,)).fetchone()
        if row is None or row["canonical_id"] in seen:
            break
        entity_id = row["canonical_id"]
        seen.add(entity_id)
    return entity_id


def _already_merged(store: Store, provisional_id: str, canonical_id: str) -> MergeResult:
    row = store.conn.execute(
        "SELECT canonical_id, aliases_moved FROM entity_merges WHERE provisional_id=?",
        (provisional_id,)).fetchone()
    if row is None:
        raise MergeError(f"unknown entity: {provisional_id}")
    if _follow_merges(store, row["canonical_id"]) != canonical_id:
        raise MergeError(
            f"{provisional_id} was already merged into {row['canonical_id']},"
            f" not {canonical_id}")
    return MergeResult(provisional_id, canonical_id, row["aliases_moved"],
                       already_merged=True)


def _record_spelling(store: Store, canonical_id: str, name: str | None) -> int:
    """Keep ``name`` as a manual alias of the canonical entity, once."""
    if not name:
        return 0
    held = store.conn.execute(
        "SELECT 1 FROM aliases WHERE entity_id=? AND name_variant=? LIMIT 1",
        (canonical_id, name)).fetchone()
    if held:
        return 0
    store.conn.execute(
        "INSERT INTO aliases (entity_id, provider, provider_id, name_variant, script)"
        " VALUES (?,?,?,?,?)",
        (canonical_id, "manual", None, name, script_of(name)))
    return 1


# ── CLI ─────────────────────────────────────────────────────────────────────
def format_queue(entries: list[dict]) -> str:
    if not entries:
        return "Review queue is empty — every entity resolved."
    lines = [f"{len(entries)} provisional entit{'y' if len(entries) == 1 else 'ies'}"
             " awaiting review:"]
    for entry in entries:
        names = " / ".join(n for n in (entry["name_ar"], entry["name_en"]) if n) or "(unnamed)"
        lines.append("")
        lines.append(f"  {entry['id']}  {names}")
        lines.append(f"    type={entry['type']} country={entry['country'] or '?'}"
                     f" created={entry['created_at']}"
                     f" sources={', '.join(entry['sources']) or 'none'}")
        for alias in entry["aliases"]:
            provider = alias["provider"]
            if alias["provider_id"]:
                provider += f":{alias['provider_id']}"
            lines.append(f"    alias {alias['name_variant']}"
                         f" [{alias['script'] or '?'}] via {provider}")
        lines.append(f"    merge: make merge FROM={entry['id']} INTO=<canonical-id>")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m arabfootball.resolve.review",
        description="List provisional entities and merge them into canonical ones.")
    parser.add_argument("--db", default="arabfootball.db", help="path to the store")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="list provisional entities (default)")
    merge_parser = sub.add_parser("merge", help="merge a provisional entity into a canonical one")
    merge_parser.add_argument("provisional", help="the provisional entity id")
    merge_parser.add_argument("canonical", help="the canonical entity id it really is")
    args = parser.parse_args(argv)

    from arabfootball.store.db import Store

    store = Store(args.db)
    try:
        if args.command == "merge":
            try:
                result = merge(store, args.provisional, args.canonical)
            except MergeError as exc:
                print(f"refused: {exc}")
                return 2
            done = "already merged" if result.already_merged else "merged"
            print(f"{done}: {result.provisional_id} -> {result.canonical_id}"
                  f" ({result.aliases_moved} alias(es) kept)")
        else:
            print(format_queue(queue(store)))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
