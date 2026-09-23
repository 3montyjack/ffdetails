"""Parser tests for Sleeper actuals, projections, injuries, and waiver bids."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ffdetails.errors import ParseError
from ffdetails.sleeper import (
    parse_actuals,
    parse_injury_tags,
    parse_projections,
    parse_waiver_bids,
    projections_url,
    stats_url,
    transactions_url,
)

STAMP = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)


class SleeperParseTests(unittest.TestCase):
    def test_actuals_keep_player_numbers_and_skip_team_rows(self) -> None:
        records = parse_actuals(
            {
                "8151": {"rush_yd": 173, "pts_ppr": 34.1, "note": "skip", "flag": True},
                "TEAM_KC": {"pts_ppr": 78.76},
                "empty": {"note": "no numbers"},
            },
            season=2026,
            week=1,
            recorded_at=STAMP,
        )
        self.assertEqual([record.player_id for record in records], ["8151"])
        self.assertEqual(records[0].stats["rush_yd"], 173)
        self.assertEqual(records[0].stats["pts_ppr"], 34.1)
        self.assertNotIn("note", records[0].stats)
        self.assertNotIn("flag", records[0].stats)
        self.assertEqual(records[0].source, "sleeper")

    def test_projections_preserve_source_order(self) -> None:
        records = parse_projections(
            {"2": {"pts_ppr": 1.0}, "1": {"pts_ppr": 99.0}},
            season=2026,
            week=3,
            season_type="post",
            recorded_at=STAMP,
        )
        self.assertEqual([record.player_id for record in records], ["2", "1"])
        self.assertEqual(records[0].season_type, "post")

    def test_stat_payload_must_be_an_object(self) -> None:
        with self.assertRaises(ParseError):
            parse_actuals([], season=2026, week=1, recorded_at=STAMP)

    def test_injury_tags_keep_published_labels(self) -> None:
        tags = parse_injury_tags(
            {
                "8733": {
                    "player_id": "8733",
                    "full_name": "Jake Hummel",
                    "position": "LB",
                    "team": "HOU",
                    "injury_status": " Questionable ",
                    "injury_body_part": "Groin",
                    "injury_notes": None,
                    "status": "Active",
                },
                "1": {"full_name": "Healthy Player", "injury_status": None},
                "2": "not-a-player",
                "12602": {
                    "full_name": "Mykel Williams",
                    "injury_status": "PUP",
                    "injury_body_part": "Knee - ACL",
                    "injury_notes": "Surgery",
                },
            },
            recorded_at=STAMP,
        )
        self.assertEqual([(tag.player_id, tag.tag) for tag in tags], [("8733", "Questionable"), ("12602", "PUP")])
        self.assertEqual(tags[0].body_part, "Groin")
        self.assertIsNone(tags[0].notes)
        self.assertEqual(tags[1].notes, "Surgery")

    def test_waiver_bids_record_the_claim_amount(self) -> None:
        bids = parse_waiver_bids(
            [
                {"type": "trade", "transaction_id": "t1", "adds": {"1": 1}, "settings": {"waiver_bid": 99}},
                {"type": "free_agent", "transaction_id": "f1", "adds": {"2": 1}},
                {
                    "type": "waiver",
                    "transaction_id": "w1",
                    "status": "complete",
                    "settings": {"waiver_bid": 27},
                    "adds": {"4046": 3},
                    "drops": {"200": 3},
                },
                {
                    "type": "waiver",
                    "transaction_id": "w2",
                    "status": "failed",
                    "settings": {"waiver_bid": 5},
                    "adds": {"11": 4, "12": 4},
                    "drops": None,
                },
                {
                    "type": "waiver",
                    "transaction_id": "w0",
                    "status": "complete",
                    "settings": {"waiver_bid": 0},
                    "adds": {"13": 1},
                },
            ],
            league_id="lg1",
            season=2026,
            week=3,
            recorded_at=STAMP,
        )
        self.assertEqual(
            [(bid.transaction_id, bid.player_id, bid.bid, bid.status) for bid in bids],
            [("w1", "4046", 27, "complete"), ("w2", "11", 5, "failed"), ("w2", "12", 5, "failed"), ("w0", "13", 0, "complete")],
        )
        self.assertEqual(bids[0].drops, ("200",))
        self.assertEqual(bids[1].drops, ())
        self.assertEqual(bids[1].roster_id, 4)

    def test_waiver_without_an_added_player_is_an_error(self) -> None:
        with self.assertRaises(ParseError):
            parse_waiver_bids(
                [{"type": "waiver", "transaction_id": "w", "status": "complete", "settings": {"waiver_bid": 3}}],
                league_id="lg",
                season=2026,
                week=1,
                recorded_at=STAMP,
            )

    def test_urls(self) -> None:
        self.assertEqual(
            stats_url(2026, 1, "regular"),
            "https://api.sleeper.app/v1/stats/nfl/regular/2026/1",
        )
        self.assertEqual(
            projections_url(2026, 3, "post"),
            "https://api.sleeper.app/v1/projections/nfl/post/2026/3",
        )
        self.assertEqual(
            transactions_url("7844", 2),
            "https://api.sleeper.app/v1/league/7844/transactions/2",
        )


if __name__ == "__main__":
    unittest.main()
