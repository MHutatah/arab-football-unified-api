"""SQLite store — the resolver's backing and the published snapshot format.

The producer may run Postgres; the schema is deliberately portable and the
snapshot everyone downloads is exactly this SQLite file.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from arabfootball.resolve.normalize import norm, xkey

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# Match state is forward-only: a stale feed must never un-finish a game, so the
# ladder is only ever climbed, never descended.
MATCH_STATUS_ORDER = ("scheduled", "live", "finished")


def _status_rank(status: str) -> int:
    if status not in MATCH_STATUS_ORDER:
        raise ValueError(f"unknown match status: {status!r}")
    return MATCH_STATUS_ORDER.index(status)


def _forward_score(incoming: int | None, stored: int | None, may_write: bool) -> int | None:
    """A score is written only by a feed that reports one and is not behind."""
    return incoming if may_write and incoming is not None else stored


class Store:
    def __init__(self, path: str = ":memory:"):
        self._grouped = False
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def atomic(self):
        """Group writes so that a failure leaves the store exactly as it was.

        Resolution writes entities and aliases before the row they were resolved
        for exists; without a boundary, a record refused half-way through would
        leave those provisional clubs behind in the review queue.
        """
        if self._grouped:            # already inside a boundary: it owns the commit
            yield
            return
        self._grouped = True
        try:
            with self.conn:          # commits on success, rolls back on any exception
                yield
        finally:
            self._grouped = False

    def _commit(self) -> None:
        """Commit, unless `atomic` is grouping these writes into one unit."""
        if not self._grouped:
            self.conn.commit()

    # ── resolver interface ──────────────────────────────────────────────────
    def find_by_provider(self, provider: str, provider_id: str,
                         type: str | None = None) -> str | None:
        """The entity a provider's own id points at, optionally within one type.

        Provider id spaces are per-type: 365scores numbers teams, competitions
        and players independently, so `649` is both a club and a league. A caller
        that knows which one it is asking for must say so, or it can be handed
        the other.
        """
        sql = "SELECT a.entity_id FROM aliases a"
        args: list[str] = [provider, provider_id]
        if type:
            sql += " JOIN entities e ON e.id=a.entity_id"
        sql += " WHERE a.provider=? AND a.provider_id=?"
        if type:
            sql += " AND e.type=?"
            args.append(type)
        row = self.conn.execute(sql + " LIMIT 1", args).fetchone()
        return row["entity_id"] if row else None

    def find_by_norm(self, type: str, country: str | None, key: str,
                     cross_script: str | None = None) -> list[str]:
        """Entities in scope matching `key` (same-script) or `cross_script`
        (consonant skeleton, for an Arabic name meeting a Latin one)."""
        sql = ("SELECT e.id, e.name_ar, e.name_en FROM entities e "
               "WHERE e.type=?" + (" AND e.country=?" if country else ""))
        args = (type, country) if country else (type,)
        out = []
        for r in self.conn.execute(sql, args):
            names = [r["name_ar"] or "", r["name_en"] or ""]
            names += [a["name_variant"] for a in self.conn.execute(
                "SELECT name_variant FROM aliases WHERE entity_id=?", (r["id"],))]
            same_script = any(norm(n) == key for n in names if n)
            # cross-script needs a long-enough skeleton: short ones collide easily
            cross = (bool(cross_script) and len(cross_script) >= 3
                     and any(xkey(n) == cross_script for n in names if n))
            if same_script or cross:
                out.append(r["id"])
        return out

    def candidates(self, type: str, country: str | None):
        sql = ("SELECT id, name_ar, name_en FROM entities WHERE type=?"
               + (" AND country=?" if country else ""))
        args = (type, country) if country else (type,)
        for r in self.conn.execute(sql, args):
            for nm in (r["name_en"], r["name_ar"]):
                if nm:
                    yield r["id"], nm

    def create_entity(self, *, type: str, name_ar=None, name_en=None,
                      country=None, meta=None, provisional=False) -> str:
        entity_id = f"{type}:{uuid.uuid4().hex[:12]}"
        self.conn.execute(
            "INSERT INTO entities (id,type,name_ar,name_en,country,meta,provisional,created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (entity_id, type, name_ar, name_en, country,
             json.dumps(meta, ensure_ascii=False) if meta else None,
             1 if provisional else 0, _now()))
        self._commit()
        return entity_id

    def add_alias(self, entity_id, provider, provider_id, name_variant, script) -> None:
        if not name_variant:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO aliases (entity_id,provider,provider_id,name_variant,script)"
            " VALUES (?,?,?,?,?)",
            (entity_id, provider, provider_id, name_variant, script))
        self._commit()

    # ── reads ───────────────────────────────────────────────────────────────
    def entity(self, entity_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        return dict(r) if r else None

    def review_queue(self) -> list[dict]:
        """Provisional entities awaiting a human decision — never hidden."""
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM entities WHERE provisional=1 ORDER BY created_at")]

    # ── archive writes ──────────────────────────────────────────────────────
    def match(self, match_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        return dict(row) if row else None

    def find_match(self, *, provider_ids: dict | None = None,
                   home_entity: str | None = None, away_entity: str | None = None,
                   kickoff_utc: str | None = None) -> dict | None:
        """Locate a stored match: by a provider's own id, else by teams + date.

        The provider id comes first and carries no date: a postponed game keeps
        its id while its kickoff moves, and matching on the id is what stops the
        reschedule from being stored as a second match.
        """
        for provider, provider_id in sorted((provider_ids or {}).items()):
            if provider_id is None:
                continue
            row = self.conn.execute(
                "SELECT * FROM matches WHERE json_extract(provider_ids, ?)=? LIMIT 1",
                ("$." + json.dumps(provider), str(provider_id))).fetchone()
            if row:
                return dict(row)
        if home_entity and away_entity and kickoff_utc:
            # Same clubs, same calendar day: the kickoff time alone drifts too
            # often between sources for an exact timestamp to be the key.
            row = self.conn.execute(
                "SELECT * FROM matches WHERE home_entity=? AND away_entity=?"
                " AND substr(kickoff_utc,1,10)=? LIMIT 1",
                (home_entity, away_entity, kickoff_utc[:10])).fetchone()
            if row:
                return dict(row)
        return None

    def upsert_match(self, *, home_entity: str, away_entity: str, kickoff_utc: str,
                     status: str, competition_id: str | None = None,
                     season: str | None = None, round: str | None = None,
                     venue_id: str | None = None, home_score: int | None = None,
                     away_score: int | None = None,
                     provider_ids: dict | None = None) -> tuple[str, str]:
        """Store one match forward-only; returns (match_id, inserted|updated|unchanged).

        A resync may only ever add to what is already recorded: the status climbs
        the ladder, a feed that is behind the stored state cannot touch the score,
        and every provider id ever seen for the match is kept.
        """
        incoming_rank = _status_rank(status)
        ids = {p: str(i) for p, i in (provider_ids or {}).items() if i is not None}
        existing = self.find_match(provider_ids=ids, home_entity=home_entity,
                                   away_entity=away_entity, kickoff_utc=kickoff_utc)
        if existing is None:
            match_id = f"match:{uuid.uuid4().hex[:12]}"
            self.conn.execute(
                "INSERT INTO matches (id,competition_id,season,round,home_entity,away_entity,"
                "kickoff_utc,venue_id,status,home_score,away_score,provider_ids,last_synced)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (match_id, competition_id, season, round, home_entity, away_entity,
                 kickoff_utc, venue_id, status, home_score, away_score,
                 json.dumps(ids, ensure_ascii=False) if ids else None, _now()))
            self._commit()
            return match_id, "inserted"

        stored_ids = json.loads(existing["provider_ids"]) if existing["provider_ids"] else {}
        # Scores are forward-only in the same sense the ladder is: only a feed
        # that has caught up with the stored state may write them. A stale pass
        # still calling a finished 2-1 a live 1-0 is ignored, while a second
        # finished pass may still correct 2-1 to 2-0 — VAR does disallow goals
        # after the whistle, and that correction comes from an equally current
        # feed rather than from one that is behind.
        may_score = incoming_rank >= _status_rank(existing["status"])
        merged = {
            "competition_id": competition_id or existing["competition_id"],
            "season": season or existing["season"],
            "round": round or existing["round"],
            "home_entity": home_entity,
            "away_entity": away_entity,
            "kickoff_utc": kickoff_utc,
            "venue_id": venue_id or existing["venue_id"],
            "status": max(status, existing["status"], key=_status_rank),
            "home_score": _forward_score(home_score, existing["home_score"], may_score),
            "away_score": _forward_score(away_score, existing["away_score"], may_score),
            "provider_ids": {**stored_ids, **ids},
        }
        previous = {column: (stored_ids if column == "provider_ids" else existing[column])
                    for column in merged}
        changed = merged != previous
        self.conn.execute(
            "UPDATE matches SET competition_id=?,season=?,round=?,home_entity=?,away_entity=?,"
            "kickoff_utc=?,venue_id=?,status=?,home_score=?,away_score=?,provider_ids=?,"
            "last_synced=? WHERE id=?",
            (merged["competition_id"], merged["season"], merged["round"],
             merged["home_entity"], merged["away_entity"], merged["kickoff_utc"],
             merged["venue_id"], merged["status"], merged["home_score"],
             merged["away_score"],
             json.dumps(merged["provider_ids"], ensure_ascii=False)
             if merged["provider_ids"] else None,
             _now(), existing["id"]))
        self._commit()
        return existing["id"], "updated" if changed else "unchanged"

    def upsert_appearance(self, *, player_entity: str, match_id: str, team_entity: str,
                          started: int | None = None, minutes: int | None = None,
                          goals: int | None = None, assists: int | None = None,
                          yellow: int | None = None, red: int | None = None) -> None:
        """Store the latest lineup facts for one player and match.

        Lineups are commonly re-fetched while a match is live.  Updating the
        existing row makes those passes both idempotent and able to fill in
        final minutes/cards once they become available.
        """
        self.conn.execute(
            """
            INSERT INTO appearances
                (player_entity, match_id, team_entity, started, minutes,
                 goals, assists, yellow, red)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_entity, match_id) DO UPDATE SET
                team_entity=excluded.team_entity,
                started=COALESCE(excluded.started, appearances.started),
                minutes=COALESCE(excluded.minutes, appearances.minutes),
                goals=COALESCE(excluded.goals, appearances.goals),
                assists=COALESCE(excluded.assists, appearances.assists),
                yellow=COALESCE(excluded.yellow, appearances.yellow),
                red=COALESCE(excluded.red, appearances.red)
            """,
            (player_entity, match_id, team_entity, started, minutes, goals,
             assists, yellow, red),
        )
        self._commit()

    def form(self, team: str, n: int = 5) -> dict:
        """Recent results derived from this store, with no live fetch."""
        from arabfootball.derive.form import form

        return form(self, team, n)

    def squad(self, team: str, season: str) -> list[dict]:
        """Season squad derived from this store, with no live fetch."""
        from arabfootball.derive.careers import squad

        return squad(self, team, season)

    def career(self, player: str) -> list[dict]:
        """Player career derived from this store, with no live fetch."""
        from arabfootball.derive.careers import career

        return career(self, player)
