"""Snapshot storage tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ffdetails.records import (
    FantasyProsProjection,
    InjuryTag,
    SleeperActual,
    WaiverBid,
    freeze_stats,
)
from ffdetails.store import RecordStore

START = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def _actual(points: float, when: datetime, player_id: str = "8151") -> SleeperActual:
    return SleeperActual(
        season=2026,
        week=1,
        player_id=player_id,
        stats=freeze_stats({"pts_ppr": points}),
        recorded_at=when,
    )


class StoreTests(unittest.TestCase):
    def test_latest_snapshot_replaces_the_view_and_history_keeps_both(self) -> None:
        store = RecordStore()
        store.add_sleeper_actuals(
            [
                _actual(10, START),
                _actual(12, START + timedelta(hours=1)),
                _actual(4, START, player_id="2"),
            ]
        )
        latest = {row.player_id: row.stats["pts_ppr"] for row in store.sleeper_actuals(2026, 1)}
        self.assertEqual(latest, {"8151": 12, "2": 4})
        history = store.sleeper_actuals(2026, 1, history=True)
        self.assertEqual([row.stats["pts_ppr"] for row in history if row.player_id == "8151"], [10, 12])
        store.close()

    def test_other_record_types_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "details.sqlite"
            with RecordStore(path) as store:
                when = START
                store.add_fantasypros_projections(
                    [
                        FantasyProsProjection(
                            season=2026,
                            week=None,
                            position="QB",
                            player_id="17298",
                            name="Josh Allen",
                            team="BUF",
                            scoring="HALF",
                            stats=freeze_stats({"fpts": 23.712}),
                            recorded_at=when,
                        )
                    ]
                )
                store.add_injury_tags(
                    [
                        InjuryTag(
                            player_id="8733",
                            tag="Questionable",
                            name="Jake Hummel",
                            team="HOU",
                            position="LB",
                            body_part="Groin",
                            notes=None,
                            recorded_at=when,
                        )
                    ]
                )
                store.add_waiver_bids(
                    [
                        WaiverBid(
                            league_id="lg",
                            season=2026,
                            week=3,
                            transaction_id="w2",
                            player_id="11",
                            roster_id=4,
                            bid=5,
                            status="failed",
                            drops=(),
                            recorded_at=when,
                        )
                    ]
                )
            with RecordStore(path) as store:
                projections = store.fantasypros_projections(2026, None, scoring="HALF")
                self.assertEqual(projections[0].stats["fpts"], 23.712)
                self.assertIsNone(projections[0].week)
                self.assertEqual(store.injury_tags()[0].tag, "Questionable")
                self.assertEqual(store.waiver_bids("lg", 2026, 3)[0].bid, 5)


if __name__ == "__main__":
    unittest.main()
