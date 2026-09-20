"""Source collectors and their shared execution contract.

`collectors.run` — the `make collect-saudi` entry point — is deliberately not
re-exported here: importing it would both shadow the module with its own `run`
function and make `python -m arabfootball.collectors.run` load the module
twice, which runpy warns about on every producer run. Import it directly:
`from arabfootball.collectors.run import run`.
"""

from arabfootball.collectors.base import Collector, RateBudget
from arabfootball.collectors.ingest import IngestResult, ingest
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
    "RateBudget",
    "Scores365Collector",
    "SeedResult",
    "StandingsCollector",
    "ingest",
    "seed_league",
]
