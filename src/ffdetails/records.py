"""Immutable records of published fantasy-football details."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping


Stats = Mapping[str, int | float]


def freeze_stats(stats: Mapping[str, int | float]) -> Stats:
    """Return an immutable copy of a stat map."""
    return MappingProxyType(dict(stats))


@dataclass(frozen=True)
class SleeperActual:
    """One player's published Sleeper stat line for a week."""

    season: int
    week: int
    player_id: str
    stats: Stats
    recorded_at: datetime
    season_type: str = "regular"
    source: str = "sleeper"


@dataclass(frozen=True)
class SleeperProjection:
    """One player's published Sleeper projection for a week."""

    season: int
    week: int
    player_id: str
    stats: Stats
    recorded_at: datetime
    season_type: str = "regular"
    source: str = "sleeper"


@dataclass(frozen=True)
class FantasyProsProjection:
    """One player's published FantasyPros consensus projection."""

    season: int
    week: int | None
    position: str
    player_id: str
    name: str
    team: str | None
    scoring: str
    stats: Stats
    recorded_at: datetime
    source: str = "fantasypros"


@dataclass(frozen=True)
class FantasyProsExpert:
    """One expert listed on a FantasyPros weekly rankings page."""

    season: int
    week: int
    position: str
    scoring: str
    expert_id: str
    name: str
    site: str | None
    accuracy_rank: int | None
    rankings_url: str | None
    recorded_at: datetime
    source: str = "fantasypros"


@dataclass(frozen=True)
class FantasyProsRank:
    """One player's rank on a published FantasyPros expert board."""

    season: int
    week: int
    position: str
    scoring: str
    expert_id: str
    expert_name: str
    accuracy_rank: int
    player_id: str
    name: str
    team: str | None
    opponent: str | None
    rank: int
    ecr: int | None
    recorded_at: datetime
    source: str = "fantasypros"


@dataclass(frozen=True)
class FantasyProsAccuracy:
    """One expert's published FantasyPros accuracy rank for a week or the season."""

    season: int
    week: int | None
    expert_id: str
    name: str
    site: str | None
    overall_rank: int
    qb: int | None
    rb: int | None
    wr: int | None
    te: int | None
    k: int | None
    dst: int | None
    recorded_at: datetime
    source: str = "fantasypros"


@dataclass(frozen=True)
class InjuryTag:
    """An injury label published for a player."""

    player_id: str
    tag: str
    name: str | None
    team: str | None
    position: str | None
    body_part: str | None
    notes: str | None
    recorded_at: datetime
    source: str = "sleeper"


@dataclass(frozen=True)
class WaiverBid:
    """A waiver claim bid published by a Sleeper league."""

    league_id: str
    season: int
    week: int
    transaction_id: str
    player_id: str
    roster_id: int
    bid: int
    status: str
    drops: tuple[str, ...]
    recorded_at: datetime
    source: str = "sleeper"
