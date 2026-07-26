"""Collect 365Scores game lineups into the appearance spine."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from arabfootball.resolve.normalize import norm, script_of

BASE_URL = "https://webws.365scores.com/web/game/"


def _first(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def _integer(record: Mapping[str, Any], *keys: str) -> int | None:
    value = _first(record, *keys)
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = _first(value, "value", "total")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coalesce(*values: int | None) -> int | None:
    return next((value for value in values if value is not None), None)


class LineupCollector:
    """Fetch and persist every member in a game's lineup."""

    def __init__(self, store, *, client: httpx.Client | None = None):
        self.store = store
        self.client = client or httpx.Client(timeout=20)

    def collect(self, *, game_id: str | int, match_id: str) -> int:
        match = self.store.match(match_id)
        if match is None:
            raise ValueError(f"unknown match: {match_id}")

        response = self.client.get(
            BASE_URL,
            params={"gameId": str(game_id), "withLineups": "true"},
        )
        response.raise_for_status()
        payload = response.json()
        game = payload.get("game", payload)
        members = game.get("members", [])
        if not isinstance(members, list):
            raise ValueError("lineup response has no members[]")

        teams = self._team_map(game, match)
        written = 0
        for member in members:
            if not isinstance(member, Mapping):
                continue
            team = teams.get(str(_first(member, "competitorId", "teamId")))
            if team is None:
                continue
            athlete = member.get("athlete")
            player = athlete if isinstance(athlete, Mapping) else member
            if player is member:
                provider_id = _first(member, "athleteId", "playerId", "id")
            else:
                provider_id = _first(player, "id", "athleteId", "playerId")
            name = _first(player, "name", "displayName", "shortName")
            if not name:
                continue

            # A lineup name/id is authoritative only inside its club.  The
            # qualified namespace prevents namesakes on different clubs from
            # being merged by global name or provider-id matching.
            player_entity = self._resolve_player(team, provider_id, name)
            stats = member.get("stats")
            stats = stats if isinstance(stats, Mapping) else {}
            self.store.upsert_appearance(
                player_entity=player_entity,
                match_id=match_id,
                team_entity=team,
                started=self._started(member),
                minutes=_coalesce(
                    _integer(member, "minutes", "minutesPlayed"),
                    _integer(stats, "minutes", "minutesPlayed"),
                ),
                goals=_coalesce(_integer(member, "goals"), _integer(stats, "goals")),
                assists=_coalesce(_integer(member, "assists"), _integer(stats, "assists")),
                yellow=_coalesce(
                    _integer(member, "yellow", "yellowCards"),
                    _integer(stats, "yellow", "yellowCards"),
                ),
                red=_coalesce(
                    _integer(member, "red", "redCards"),
                    _integer(stats, "red", "redCards"),
                ),
            )
            written += 1
        return written

    def _resolve_player(self, team: str, provider_id: Any, name: str) -> str:
        """Resolve a lineup identity only within its club.

        Some lineup records omit an athlete id, so a normalized name becomes
        the stable provider key in that club's namespace.
        """
        provider = f"365scores:{team}"
        scoped_id = str(provider_id) if provider_id is not None else f"name:{norm(name)}"
        existing = self.store.find_by_provider(provider, scoped_id)
        if existing:
            self.store.add_alias(existing, provider, scoped_id, name, script_of(name))
            return existing
        entity_id = self.store.create_entity(
            type="player",
            name_ar=name if script_of(name) == "ar" else None,
            name_en=name if script_of(name) == "en" else None,
            meta={"club_scope": team},
            provisional=True,
        )
        self.store.add_alias(entity_id, provider, scoped_id, name, script_of(name))
        return entity_id

    @staticmethod
    def _team_map(game: Mapping[str, Any], match: Mapping[str, Any]) -> dict[str, str]:
        result = {}
        for keys, entity in (
            (("homeCompetitor", "homeTeam"), match["home_entity"]),
            (("awayCompetitor", "awayTeam"), match["away_entity"]),
        ):
            item = _first(game, *keys)
            if isinstance(item, Mapping):
                provider_id = _first(item, "id", "competitorId", "teamId")
                if provider_id is not None:
                    result[str(provider_id)] = entity
        return result

    @staticmethod
    def _started(member: Mapping[str, Any]) -> int | None:
        value = _first(member, "started", "isStarter", "starting")
        if value is not None:
            return int(bool(value))
        status = member.get("status")
        if isinstance(status, str):
            return int(status.lower() in {"starter", "starting", "lineup"})
        return None
