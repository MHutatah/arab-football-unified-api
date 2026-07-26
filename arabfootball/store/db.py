"""SQLite store — the resolver's backing and the published snapshot format.

The producer may run Postgres; the schema is deliberately portable and the
snapshot everyone downloads is exactly this SQLite file.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from arabfootball.resolve.normalize import norm, xkey

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.conn.close()

    # ── resolver interface ──────────────────────────────────────────────────
    def find_by_provider(self, provider: str, provider_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT entity_id FROM aliases WHERE provider=? AND provider_id=? LIMIT 1",
            (provider, provider_id)).fetchone()
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
        self.conn.commit()
        return entity_id

    def add_alias(self, entity_id, provider, provider_id, name_variant, script) -> None:
        if not name_variant:
            return
        self.conn.execute(
            "INSERT OR IGNORE INTO aliases (entity_id,provider,provider_id,name_variant,script)"
            " VALUES (?,?,?,?,?)",
            (entity_id, provider, provider_id, name_variant, script))
        self.conn.commit()

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
        self.conn.commit()
