"""Head-to-head records derived from finished matches."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arabfootball.store.db import Store


def h2h(store: Store, a: str, b: str) -> dict:
    """Return finished meetings and the W/D/L record from ``a``'s perspective.

    Unknown clubs and clubs with no shared history naturally produce an empty
    record.  Scheduled and live fixtures are not part of meeting history.
    """
    summary = {"wins": 0, "draws": 0, "losses": 0}
    if a == b:
        return {"meetings": [], "summary": summary}

    rows = store.conn.execute(
        """
        SELECT *
        FROM matches
        WHERE status = 'finished'
          AND (
            (home_entity = ? AND away_entity = ?)
            OR (home_entity = ? AND away_entity = ?)
          )
        ORDER BY kickoff_utc DESC, id DESC
        """,
        (a, b, b, a),
    ).fetchall()

    meetings = [dict(row) for row in rows]
    for meeting in meetings:
        if meeting["home_entity"] == a:
            goals_for, goals_against = meeting["home_score"], meeting["away_score"]
        else:
            goals_for, goals_against = meeting["away_score"], meeting["home_score"]

        # A finished row should have scores. If an incomplete provider row slips
        # through, keep the meeting but do not invent a result for the summary.
        if goals_for is None or goals_against is None:
            continue
        if goals_for > goals_against:
            summary["wins"] += 1
        elif goals_for == goals_against:
            summary["draws"] += 1
        else:
            summary["losses"] += 1

    return {"meetings": meetings, "summary": summary}
