import json

from arabfootball.collectors.base import Collector
from arabfootball.store.db import Store


class FailingCollector(Collector):
    name = "deliberately-failing"

    def _collect(self):
        raise ConnectionError("source is down")


class CountingCollector(Collector):
    name = "counting"

    def _collect(self):
        self.count_inserted(2)
        self.count_updated()
        return [{"id": 1}, {"id": 2}, {"id": 3}]


def test_failing_collector_is_empty_and_observable():
    store = Store(":memory:")

    assert FailingCollector(store).collect() == []

    run = store.conn.execute("SELECT * FROM source_runs").fetchone()
    assert run["collector"] == "deliberately-failing"
    assert run["status"] == "failed"
    assert run["finished_at"] is not None
    assert (run["inserted"], run["updated"]) == (0, 0)
    assert json.loads(run["errors"]) == [
        {"type": "ConnectionError", "message": "source is down"}
    ]
    store.close()


def test_successful_collector_records_counts():
    store = Store(":memory:")

    assert CountingCollector(store).collect() == [{"id": 1}, {"id": 2}, {"id": 3}]

    run = store.conn.execute("SELECT * FROM source_runs").fetchone()
    assert run["status"] == "ok"
    assert (run["inserted"], run["updated"]) == (2, 1)
    assert json.loads(run["errors"]) == []
    store.close()


def test_rate_budget_waits_before_exceeding_source_allowance():
    store = Store(":memory:")
    elapsed = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        elapsed[0] += seconds

    collector = CountingCollector(
        store,
        rate_budget=2,
        rate_period_seconds=10,
        clock=lambda: elapsed[0],
        sleep=sleep,
    )

    collector.collect()
    collector.collect()
    collector.collect()

    assert sleeps == [10.0]
    assert store.conn.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0] == 3
    store.close()


def test_non_list_collector_result_fails_soft():
    class InvalidCollector(Collector):
        name = "invalid"

        def _collect(self):
            return None

    store = Store(":memory:")
    assert InvalidCollector(store).collect() == []
    run = store.conn.execute("SELECT status, errors FROM source_runs").fetchone()
    assert run["status"] == "failed"
    assert json.loads(run["errors"])[0]["type"] == "TypeError"
    store.close()
