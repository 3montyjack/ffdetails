"""Parser tests for FantasyPros consensus projections."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ffdetails.errors import ParseError
from ffdetails.fantasypros import parse_projections, projections_url

STAMP = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)

QB_HTML = """
<table>
<thead>
<tr><td>&nbsp;</td><td colspan="5"><b>PASSING</b></td><td colspan="3"><b>RUSHING</b></td><td colspan="2"><b>MISC</b></td></tr>
<tr>
<th>Player</th><th>ATT</th><th>CMP</th><th>YDS</th><th>TDS</th><th>INTS</th>
<th>ATT</th><th>YDS</th><th>TDS</th><th>FL</th><th>FPTS</th>
</tr>
</thead>
<tbody>
<tr class="mpb-player-17298 LACBUF">
  <td class="player-label"><a class="player-name fp-id-17298" fp-player-name="Josh Allen">Josh Allen</a> BUF</td>
  <td class="center">31.2</td>
  <td class="center">20.7</td>
  <td class="center">248.5</td>
  <td class="center">1.8</td>
  <td class="center">0.8</td>
  <td class="center">7.4</td>
  <td class="center">35.0</td>
  <td class="center">0.7</td>
  <td class="center">0.2</td>
  <td class="center" data-sort-value="23.712">23.7</td>
</tr>
<tr class="mpb-player-16413">
  <td><a class="fp-id-16413" fp-player-name="Patrick Mahomes II">Patrick Mahomes II</a> KC</td>
  <td>33.6</td><td>22.9</td><td>258.5</td><td>2.1</td><td>0.6</td>
  <td>4.2</td><td>22.4</td><td>0.3</td><td>0.2</td>
  <td data-sort-value="21.542">21.5</td>
</tr>
</tbody>
</table>
"""

DST_HTML = """
<thead>
<tr><th>Player</th><th>SACK</th><th>INT</th><th>FR</th><th>FF</th><th>TD</th><th>SAFETY</th><th>PA</th><th>YDS AGN</th><th>FPTS</th></tr>
</thead>
<tbody>
<tr class="mpb-player-8040 CARCLE">
  <td><a class="fp-id-8040" fp-player-name="Carolina Panthers">Carolina Panthers</a></td>
  <td>3.3</td><td>0.7</td><td>0.6</td><td>0.7</td><td>0.1</td><td>0.0</td><td>19.8</td><td>302.3</td>
  <td data-sort-value="7.696">7.7</td>
</tr>
</tbody>
"""

SEASON_RB_HTML = """
<thead>
<tr><td>&nbsp;</td><td>&nbsp;</td><td colspan="3"><b>RUSHING</b></td><td colspan="3"><b>RECEIVING</b></td><td colspan="2"><b>MISC</b></td></tr>
<tr><th>Player</th><th>BYE</th><th>ATT</th><th>YDS</th><th>TDS</th><th>REC</th><th>YDS</th><th>TDS</th><th>FL</th><th>FPTS</th></tr>
</thead>
<tbody>
<tr class="mpb-player-22968">
  <td><a class="fp-id-22968" fp-player-name="Jahmyr Gibbs">Jahmyr Gibbs</a> DET</td>
  <td>6</td><td>268.5</td><td>1,419.3</td><td>13.2</td><td>70.4</td><td>566.5</td><td>4.1</td><td>1.1</td>
  <td data-sort-value="370.429">370.4</td>
</tr>
</tbody>
"""


class FantasyProsParseTests(unittest.TestCase):
    def test_qb_rows_keep_published_order_and_precise_points(self) -> None:
        records = parse_projections(
            QB_HTML,
            season=2026,
            week=3,
            position="qb",
            scoring="half",
            recorded_at=STAMP,
        )
        self.assertEqual([record.player_id for record in records], ["17298", "16413"])
        self.assertEqual(records[0].name, "Josh Allen")
        self.assertEqual(records[0].team, "BUF")
        self.assertEqual(records[0].position, "QB")
        self.assertEqual(records[0].scoring, "HALF")
        self.assertEqual(records[0].stats["pass_att"], 31.2)
        self.assertEqual(records[0].stats["fpts"], 23.712)
        self.assertGreater(records[1].stats["fpts"], 0)
        self.assertLess(records[0].stats["fpts"], 100)
        self.assertEqual(records[0].source, "fantasypros")

    def test_dst_has_no_team_abbreviation(self) -> None:
        records = parse_projections(
            DST_HTML, season=2026, week=3, position="DST", scoring="PPR", recorded_at=STAMP
        )
        self.assertEqual(records[0].name, "Carolina Panthers")
        self.assertIsNone(records[0].team)
        self.assertEqual(records[0].stats["sack"], 3.3)
        self.assertEqual(records[0].stats["yds_allowed"], 302.3)
        self.assertEqual(records[0].stats["fpts"], 7.696)

    def test_season_long_week_is_empty(self) -> None:
        records = parse_projections(
            DST_HTML, season=2026, week=None, position="DST", scoring="STD", recorded_at=STAMP
        )
        self.assertIsNone(records[0].week)

    def test_season_table_records_bye_and_thousands(self) -> None:
        records = parse_projections(
            SEASON_RB_HTML, season=2026, week=None, position="RB", scoring="PPR", recorded_at=STAMP
        )
        self.assertEqual(records[0].stats["bye"], 6.0)
        self.assertEqual(records[0].stats["rush_yd"], 1419.3)
        self.assertEqual(records[0].stats["fpts"], 370.429)
        self.assertIsNone(records[0].week)

    def test_column_mismatch_raises(self) -> None:
        html = """
        <thead>
        <tr><td></td><td colspan="5">PASSING</td><td colspan="3">RUSHING</td><td colspan="2">MISC</td></tr>
        <tr><th>Player</th><th>ATT</th><th>CMP</th><th>YDS</th><th>TDS</th><th>INTS</th><th>ATT</th><th>YDS</th><th>TDS</th><th>FL</th><th>FPTS</th></tr>
        </thead>
        <tbody>
        <tr class="mpb-player-1"><td><a class="fp-id-1" fp-player-name="A">A</a> BUF</td><td>1</td></tr>
        </tbody>
        """
        with self.assertRaises(ParseError):
            parse_projections(html, season=2026, week=1, position="QB", scoring="HALF", recorded_at=STAMP)

    def test_missing_table_raises(self) -> None:
        with self.assertRaises(ParseError):
            parse_projections("<html></html>", season=2026, week=1, position="RB", scoring="HALF", recorded_at=STAMP)

    def test_urls_encode_week_and_scoring(self) -> None:
        self.assertEqual(
            projections_url("RB", 3, "PPR"),
            "https://www.fantasypros.com/nfl/projections/rb.php?week=3&scoring=PPR",
        )
        self.assertEqual(
            projections_url("QB", None, "HALF"),
            "https://www.fantasypros.com/nfl/projections/qb.php?week=draft&scoring=HALF",
        )


if __name__ == "__main__":
    unittest.main()
