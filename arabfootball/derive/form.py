"""Recent form derived from the match archive."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arabfootball.store.db import Store


def form(store: Store, team: str, n: int = 5) -> dict:
    """Return a team's latest finished matches and W/D/L summary.

    Results are calculated from ``team``'s perspective, irrespective of whether
    it was the home or away side. Accepting a store instead of a provider client
    keeps this derivation entirely offline.
    """
    empty = {
        "team": team,
        "matches": [],
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "points": 0,
    }
    if n <= 0:
        return empty

    rows = store.conn.execute(
        """
        SELECT *
        FROM matches
        WHERE status = 'finished'
          AND (home_entity = ? OR away_entity = ?)
        ORDER BY kickoff_utc DESC, id DESC
        LIMIT ?
        """,
        (team, team, n),
    ).fetchall()

    matches = []
    wins = draws = losses = points = 0
    for row in rows:
        match = dict(row)
        is_home = match["home_entity"] == team
        goals_for = match["home_score"] if is_home else match["away_score"]
        goals_against = match["away_score"] if is_home else match["home_score"]

        if goals_for > goals_against:
            result, match_points = "W", 3
            wins += 1
        elif goals_for == goals_against:
            result, match_points = "D", 1
            draws += 1
        else:
            result, match_points = "L", 0
            losses += 1

        points += match_points
        match.update(
            {
                "opponent": match["away_entity"] if is_home else match["home_entity"],
                "goals_for": goals_for,
                "goals_against": goals_against,
                "result": result,
                "points": match_points,
            }
        )
        matches.append(match)

    return {
        "team": team,
        "matches": matches,
        "played": len(matches),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points": points,
    }
