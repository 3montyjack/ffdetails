"""Pull published details and append them to a store."""

from __future__ import annotations

from datetime import datetime

from ffdetails.fantasypros import POSITIONS, FantasyProsSource
from ffdetails.records import (
    FantasyProsProjection,
    FantasyProsRank,
    InjuryTag,
    SleeperActual,
    SleeperProjection,
    WaiverBid,
)
from ffdetails.sleeper import SleeperSource
from ffdetails.store import RecordStore


class Recorder:
    """Record source snapshots.

    The methods below store the published records. They leave lineup choices
    and waiver bid amounts to the caller.
    """

    def __init__(
        self,
        store: RecordStore,
        sleeper: SleeperSource | None = None,
        fantasypros: FantasyProsSource | None = None,
    ) -> None:
        self.store = store
        self.sleeper = sleeper or SleeperSource()
        self.fantasypros = fantasypros or FantasyProsSource()

    def record_sleeper_actuals(
        self,
        season: int,
        week: int,
        *,
        season_type: str = "regular",
        recorded_at: datetime | None = None,
    ) -> list[SleeperActual]:
        records = self.sleeper.actuals(
            season, week, season_type=season_type, recorded_at=recorded_at
        )
        self.store.add_sleeper_actuals(records)
        return records

    def record_sleeper_projections(
        self,
        season: int,
        week: int,
        *,
        season_type: str = "regular",
        recorded_at: datetime | None = None,
    ) -> list[SleeperProjection]:
        records = self.sleeper.projections(
            season, week, season_type=season_type, recorded_at=recorded_at
        )
        self.store.add_sleeper_projections(records)
        return records

    def record_fantasypros_projections(
        self,
        season: int,
        week: int | None,
        *,
        positions: tuple[str, ...] | list[str] = POSITIONS,
        scoring: str = "HALF",
        recorded_at: datetime | None = None,
    ) -> list[FantasyProsProjection]:
        records = self.fantasypros.projections(
            season,
            week,
            positions=positions,
            scoring=scoring,
            recorded_at=recorded_at,
        )
        self.store.add_fantasypros_projections(records)
        return records

    def record_fantasypros_ranks(
        self,
        season: int,
        week: int,
        *,
        positions: tuple[str, ...] | list[str] = POSITIONS,
        scoring: str = "HALF",
        recorded_at: datetime | None = None,
    ) -> list[FantasyProsRank]:
        experts, ranks = self.fantasypros.positional_ranks(
            season,
            week,
            positions=positions,
            scoring=scoring,
            recorded_at=recorded_at,
        )
        self.store.add_fantasypros_experts(experts)
        self.store.add_fantasypros_ranks(ranks)
        return ranks

    def record_injury_tags(
        self, *, recorded_at: datetime | None = None
    ) -> list[InjuryTag]:
        records = self.sleeper.injury_tags(recorded_at=recorded_at)
        self.store.add_injury_tags(records)
        return records

    def record_waiver_bids(
        self,
        league_id: str,
        season: int,
        week: int,
        *,
        recorded_at: datetime | None = None,
    ) -> list[WaiverBid]:
        records = self.sleeper.waiver_bids(
            league_id, season, week, recorded_at=recorded_at
        )
        self.store.add_waiver_bids(records)
        return records
