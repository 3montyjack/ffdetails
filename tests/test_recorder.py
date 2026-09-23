"""Recorder tests with an in-memory HTTP map."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ffdetails.fantasypros import FantasyProsSource
from ffdetails.recorder import Recorder
from ffdetails.sleeper import SleeperSource
from ffdetails.store import RecordStore

STAMP = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)

QB_HTML = """
<thead>
<tr><td></td><td colspan="5">PASSING</td><td colspan="3">RUSHING</td><td colspan="2">MISC</td></tr>
<tr><th>Player</th><th>ATT</th><th>CMP</th><th>YDS</th><th>TDS</th><th>INTS</th><th>ATT</th><th>YDS</th><th>TDS</th><th>FL</th><th>FPTS</th></tr>
</thead>
<tbody>
<tr class="mpb-player-1">
  <td><a class="fp-id-1" fp-player-name="A">A</a> BUF</td>
  <td>1</td><td>1</td><td>1</td><td>1</td><td>1</td>
  <td>1</td><td>1</td><td>1</td><td>1</td>
  <td data-sort-value="9.5">9.5</td>
</tr>
</tbody>
"""


class MapClient:
    def __init__(self, json_map: dict[str, object], text_map: dict[str, str]) -> None:
        self.json_map = json_map
        self.text_map = text_map
        self.urls: list[str] = []

    def get_json(self, url: str) -> object:
        self.urls.append(url)
        return self.json_map[url]

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.text_map[url]


class RecorderTests(unittest.TestCase):
    def test_recorder_appends_each_dataset(self) -> None:
        client = MapClient(
            json_map={
                "https://api.sleeper.app/v1/stats/nfl/regular/2026/1": {"9": {"pts_ppr": 3}},
                "https://api.sleeper.app/v1/projections/nfl/regular/2026/3": {"9": {"pts_ppr": 8.5}},
                "https://api.sleeper.app/v1/players/nfl": {
                    "9": {"player_id": "9", "full_name": "Nine", "injury_status": "Out"}
                },
                "https://api.sleeper.app/v1/league/lg/transactions/3": [
                    {
                        "type": "waiver",
                        "transaction_id": "w",
                        "status": "complete",
                        "settings": {"waiver_bid": 12},
                        "adds": {"9": 1},
                    }
                ],
            },
            text_map={
                "https://www.fantasypros.com/nfl/projections/qb.php?week=3&scoring=HALF": QB_HTML
            },
        )
        store = RecordStore()
        recorder = Recorder(store, SleeperSource(client), FantasyProsSource(client))
        self.assertEqual(len(recorder.record_sleeper_actuals(2026, 1, recorded_at=STAMP)), 1)
        self.assertEqual(len(recorder.record_sleeper_projections(2026, 3, recorded_at=STAMP)), 1)
        self.assertEqual(
            len(recorder.record_fantasypros_projections(2026, 3, positions=("QB",), recorded_at=STAMP)),
            1,
        )
        self.assertEqual(len(recorder.record_injury_tags(recorded_at=STAMP)), 1)
        bids = recorder.record_waiver_bids("lg", 2026, 3, recorded_at=STAMP)
        self.assertEqual(bids[0].bid, 12)
        self.assertEqual(store.sleeper_actuals(2026, 1)[0].stats["pts_ppr"], 3)
        self.assertEqual(store.injury_tags()[0].tag, "Out")
        self.assertEqual(store.fantasypros_projections(2026, 3)[0].stats["fpts"], 9.5)
        store.close()


if __name__ == "__main__":
    unittest.main()
