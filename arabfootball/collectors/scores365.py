"""Fetch and normalize 365Scores fixtures and results."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from arabfootball.collectors.base import Collector

BASE_URL = "https://webws.365scores.com/web/games/"
SAUDI_PRO_LEAGUE_ID = "649"


def _as_date(value: date | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _kickoff_utc(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("game has no startTime")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("game startTime has no timezone")
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def _score(value: Any) -> int | None:
    if value is None:
        return None
    number = float(value)
    if not number.is_integer():
        raise ValueError(f"non-integral football score: {value}")
    return int(number)


def _status(game: Mapping[str, Any]) -> str:
    """Collapse provider states onto the store's three match states."""
    text = " ".join(
        str(game.get(key, "")).casefold()
        for key in ("statusText", "shortStatusText")
    )
    if any(word in text for word in ("ended", "final", "full time", "after penalties")):
        return "finished"
    if any(word in text for word in ("scheduled", "not started", "postponed", "cancelled")):
        return "scheduled"

    group = game.get("statusGroup")
    if group in (3, 4):
        return "finished"
    if group == 2:
        return "scheduled"
    return "live"


def _team(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("id") is None or not value.get("name"):
        raise ValueError("game has an invalid competitor")
    return {
        "name": str(value["name"]),
        "provider_ids": {"365scores": str(value["id"])},
    }


class Scores365Collector(Collector):
    """Collect a season through bounded, inclusive date windows."""

    name = "365scores-fixtures"

    def __init__(
        self,
        store,
        *,
        client: httpx.Client | None = None,
        window_days: int = 31,
        **kwargs: Any,
    ):
        super().__init__(store, **kwargs)
        if window_days < 1:
            raise ValueError("window_days must be positive")
        self.client = client or httpx.Client(timeout=20)
        self.window_days = window_days

    def _collect(
        self,
        *,
        season_start: date | str,
        season_end: date | str,
        competition_id: str | int = SAUDI_PRO_LEAGUE_ID,
    ) -> list[dict[str, Any]]:
        start = _as_date(season_start)
        end = _as_date(season_end)
        if end < start:
            raise ValueError("season_end must not precede season_start")

        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor = start
        request_number = 0
        while cursor <= end:
            window_end = min(end, cursor + timedelta(days=self.window_days - 1))
            # Collector.collect acquired the first request from this source's
            # budget; every page after it consumes another allowance.
            if request_number:
                self.rate_budget.acquire()
            response = self.client.get(
                BASE_URL,
                params={
                    "competitions": str(competition_id),
                    "startDate": cursor.isoformat(),
                    "endDate": window_end.isoformat(),
                },
            )
            response.raise_for_status()
            payload = response.json()
            games = payload.get("games") if isinstance(payload, Mapping) else None
            if not isinstance(games, list):
                raise ValueError("games response has no games[]")
            for game in games:
                record = self._normalize(game, competition_id)
                game_id = record["provider_ids"]["365scores"]
                if game_id not in seen:
                    seen.add(game_id)
                    records.append(record)
            cursor = window_end + timedelta(days=1)
            request_number += 1
        return records

    @staticmethod
    def _normalize(game: Any, competition_id: str | int) -> dict[str, Any]:
        if not isinstance(game, Mapping) or game.get("id") is None:
            raise ValueError("games[] contains an invalid game")
        return {
            "home_team": _team(game.get("homeCompetitor")),
            "away_team": _team(game.get("awayCompetitor")),
            "kickoff_utc": _kickoff_utc(game.get("startTime")),
            "status": _status(game),
            "home_score": _score(
                game.get("homeCompetitor", {}).get("score")
                if isinstance(game.get("homeCompetitor"), Mapping)
                else None
            ),
            "away_score": _score(
                game.get("awayCompetitor", {}).get("score")
                if isinstance(game.get("awayCompetitor"), Mapping)
                else None
            ),
            "provider_ids": {"365scores": str(game["id"])},
            "competition_provider_ids": {"365scores": str(competition_id)},
        }
