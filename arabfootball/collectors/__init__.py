"""Source collectors and their shared execution contract."""

from arabfootball.collectors.base import Collector, RateBudget
from arabfootball.collectors.ingest import IngestResult, ingest
from arabfootball.collectors.scores365 import Scores365Collector

__all__ = ["Collector", "IngestResult", "RateBudget", "Scores365Collector", "ingest"]
