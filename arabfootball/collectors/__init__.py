"""Source collectors and their shared execution contract."""

from arabfootball.collectors.base import Collector, RateBudget
from arabfootball.collectors.ingest import (
    IngestResult,
    ProvisionalRate,
    ingest,
    provisional_rate,
)
from arabfootball.collectors.scores365 import Scores365Collector
from arabfootball.collectors.standings import (
    SAUDI_PRO_LEAGUE,
    LeagueSeed,
    SeedResult,
    StandingsCollector,
    seed_league,
)

__all__ = [
    "SAUDI_PRO_LEAGUE",
    "Collector",
    "IngestResult",
    "LeagueSeed",
    "ProvisionalRate",
    "RateBudget",
    "Scores365Collector",
    "SeedResult",
    "StandingsCollector",
    "ingest",
    "provisional_rate",
    "seed_league",
]
