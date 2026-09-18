"""Source collectors and their shared execution contract."""

from arabfootball.collectors.base import Collector, RateBudget
from arabfootball.collectors.ingest import IngestError, IngestResult, ingest
from arabfootball.collectors.scores365 import Scores365Collector

__all__ = ["Collector", "IngestError", "IngestResult", "RateBudget",
           "Scores365Collector", "ingest"]
