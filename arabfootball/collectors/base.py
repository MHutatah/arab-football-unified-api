"""Common collector execution, rate limiting, and run observability."""
from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RateBudget:
    """A sliding-window request budget.

    ``acquire`` waits when the source has exhausted its allowance.  A budget
    belongs to one collector instance, so one slow or restrictive provider
    never throttles another.
    """

    def __init__(
        self,
        requests: int,
        *,
        period_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if requests < 1:
            raise ValueError("rate budget must allow at least one request")
        if period_seconds <= 0:
            raise ValueError("rate budget period must be positive")
        self.requests = requests
        self.period_seconds = period_seconds
        self._clock = clock
        self._sleep = sleep
        self._used: deque[float] = deque()

    def acquire(self) -> None:
        """Consume one request from the budget, waiting if necessary."""
        now = self._clock()
        self._discard_expired(now)
        if len(self._used) >= self.requests:
            delay = self.period_seconds - (now - self._used[0])
            if delay > 0:
                self._sleep(delay)
            now = self._clock()
            self._discard_expired(now)
        self._used.append(now)

    def _discard_expired(self, now: float) -> None:
        while self._used and now - self._used[0] >= self.period_seconds:
            self._used.popleft()


class Collector(ABC):
    """Base interface for a fail-soft source collector.

    Subclasses implement :meth:`_collect`; callers use :meth:`collect`.
    ``collect`` always returns a list.  A source timeout, malformed response, or
    other source error is recorded in ``source_runs`` and returns ``[]`` rather
    than escaping into the wider pipeline.
    """

    name: str

    def __init__(
        self,
        store,
        *,
        rate_budget: int = 60,
        rate_period_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.store = store
        self.rate_budget = RateBudget(
            rate_budget,
            period_seconds=rate_period_seconds,
            clock=clock,
            sleep=sleep,
        )
        self._active_run_id: str | None = None

    def collect(self, *args: Any, **kwargs: Any) -> list[Any]:
        """Run once, recording its outcome and returning an empty list on failure."""
        run_id = uuid.uuid4().hex
        started_at = _now()
        self.store.conn.execute(
            """INSERT INTO source_runs
               (id, collector, started_at, status, inserted, updated, errors)
               VALUES (?, ?, ?, ?, 0, 0, ?)""",
            (run_id, self.name, started_at, "partial", json.dumps([])),
        )
        self.store.conn.commit()
        self._active_run_id = run_id

        try:
            self.rate_budget.acquire()
            records = self._collect(*args, **kwargs)
            if not isinstance(records, list):
                raise TypeError("collector must return a list")
        except Exception as exc:
            errors = [{"type": type(exc).__name__, "message": str(exc)}]
            self._finish_run(run_id, status="failed", errors=errors)
            self._active_run_id = None
            return []

        self._finish_run(run_id, status="ok", errors=[])
        self._active_run_id = None
        return records

    def _finish_run(self, run_id: str, *, status: str, errors: list[dict[str, str]]) -> None:
        self.store.conn.execute(
            """UPDATE source_runs
               SET finished_at=?, status=?, errors=?
               WHERE id=?""",
            (_now(), status, json.dumps(errors, ensure_ascii=False), run_id),
        )
        self.store.conn.commit()

    def count_inserted(self, count: int = 1) -> None:
        """Add successfully inserted rows to the active run's count."""
        self._increment_latest("inserted", count)

    def count_updated(self, count: int = 1) -> None:
        """Add successfully updated rows to the active run's count."""
        self._increment_latest("updated", count)

    def _increment_latest(self, column: str, count: int) -> None:
        if count < 0:
            raise ValueError("run counts cannot be negative")
        if self._active_run_id is None:
            raise RuntimeError("run counts can only be changed while collecting")
        self.store.conn.execute(
            f"UPDATE source_runs SET {column}={column}+? WHERE id=?",
            (count, self._active_run_id),
        )
        self.store.conn.commit()

    @abstractmethod
    def _collect(self, *args: Any, **kwargs: Any) -> list[Any]:
        """Fetch one source and return normalized records.

        Exceptions are allowed here: the public :meth:`collect` boundary turns
        them into an observable, graceful empty result.
        """
        raise NotImplementedError
