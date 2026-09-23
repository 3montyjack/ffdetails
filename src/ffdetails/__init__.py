"""Record fantasy-football details.

ffdetails stores Sleeper actuals, Sleeper projections, FantasyPros consensus
projections, FantasyPros positional ranks, FantasyPros accuracy windows,
injury tags, and waiver bids. Lineup and waiver-bid decisions stay outside
this package.
"""

from ffdetails.errors import FfdetailsError, FetchError, ParseError
from ffdetails.fantasypros import (
    FantasyProsSource,
    choose_positional_experts,
    hybrid_board,
    positional_sources,
    rank_spreads,
)
from ffdetails.http import UrllibClient
from ffdetails.recorder import Recorder
from ffdetails.records import (
    FantasyProsAccuracy,
    FantasyProsExpert,
    FantasyProsProjection,
    FantasyProsRank,
    InjuryTag,
    SleeperActual,
    SleeperProjection,
    WaiverBid,
)
from ffdetails.sleeper import SleeperSource
from ffdetails.store import RecordStore

__all__ = [
    "FantasyProsAccuracy",
    "FantasyProsExpert",
    "FantasyProsProjection",
    "FantasyProsRank",
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
    "choose_positional_experts",
    "hybrid_board",
    "positional_sources",
    "rank_spreads",
]

__version__ = "0.1.0"
