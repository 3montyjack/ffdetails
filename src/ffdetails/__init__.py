"""Record fantasy-football details.

ffdetails stores Sleeper actuals, Sleeper projections, FantasyPros consensus
projections, injury tags, and waiver bids. Lineup and waiver-bid decisions
stay outside this package.
"""

from ffdetails.errors import FfdetailsError, FetchError, ParseError
from ffdetails.fantasypros import FantasyProsSource
from ffdetails.http import UrllibClient
from ffdetails.recorder import Recorder
from ffdetails.records import (
    FantasyProsProjection,
    InjuryTag,
    SleeperActual,
    SleeperProjection,
    WaiverBid,
)
from ffdetails.sleeper import SleeperSource
from ffdetails.store import RecordStore

__all__ = [
    "FantasyProsProjection",
    "FantasyProsSource",
    "FetchError",
    "FfdetailsError",
    "InjuryTag",
    "ParseError",
    "RecordStore",
    "Recorder",
    "SleeperActual",
    "SleeperProjection",
    "SleeperSource",
    "UrllibClient",
    "WaiverBid",
]

__version__ = "0.1.0"
