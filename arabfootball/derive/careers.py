"""Squads and player careers derived from the appearance archive."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arabfootball.store.db import Store


def squad(store: Store, team: str, season: str) -> list[dict]:
    """List players who appeared for ``team`` in ``season``.

    A player-match row is one appearance, irrespective of whether the player
    started.  Unknown teams and seasons naturally return an empty list.
    """
    rows = store.conn.execute(
        """
        SELECT
            a.player_entity AS player,
            e.name_ar,
            e.name_en,
            COUNT(*) AS appearances
        FROM appearances a
        JOIN matches m ON m.id = a.match_id
        JOIN entities e ON e.id = a.player_entity
        WHERE a.team_entity = ? AND m.season = ?
        GROUP BY a.player_entity, e.name_ar, e.name_en
        ORDER BY appearances DESC, a.player_entity
        """,
        (team, season),
    ).fetchall()
    return [dict(row) for row in rows]


def career(store: Store, player: str) -> list[dict]:
    """Return a player's chronological club stints.

    Consecutive appearances for the same club form a stint.  A transfer between
    two appearances is also a boundary when it involves that club; this keeps a
    return to a former club as a distinct stint even if the intermediate club
    has no recorded appearances.
    """
    appearances = store.conn.execute(
        """
        SELECT
            a.team_entity AS club,
            m.kickoff_utc AS appeared_at,
            COALESCE(a.goals, 0) AS goals,
            m.id AS match_id
        FROM appearances a
        JOIN matches m ON m.id = a.match_id
        WHERE a.player_entity = ?
        ORDER BY m.kickoff_utc, m.id
        """,
        (player,),
    ).fetchall()
    transfers = store.conn.execute(
        """
        SELECT date, from_entity, to_entity
        FROM transfers
        WHERE player_entity = ? AND date IS NOT NULL
        ORDER BY date, id
        """,
        (player,),
    ).fetchall()

    stints: list[dict] = []
    previous_date: str | None = None
    for row in appearances:
        club = row["club"]
        transfer_boundary = previous_date is not None and any(
            previous_date < transfer["date"] <= row["appeared_at"]
            and club in (transfer["from_entity"], transfer["to_entity"])
            for transfer in transfers
        )
        if not stints or stints[-1]["club"] != club or transfer_boundary:
            stints.append(
                {
                    "club": club,
                    "first_appearance": row["appeared_at"],
                    "last_appearance": row["appeared_at"],
                    "apps": 1,
                    "goals": row["goals"],
                }
            )
        else:
            stint = stints[-1]
            stint["last_appearance"] = row["appeared_at"]
            stint["apps"] += 1
            stint["goals"] += row["goals"]
        previous_date = row["appeared_at"]

    return stints
