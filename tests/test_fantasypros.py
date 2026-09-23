"""Parser tests for FantasyPros consensus projections."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ffdetails.errors import ParseError
from ffdetails.fantasypros import (
    choose_positional_experts,
    hybrid_board,
    parse_expert_ranks,
    parse_projections,
    parse_rank_experts,
    projections_url,
    rankings_url,
)
from ffdetails.records import FantasyProsExpert, FantasyProsRank
from ffdetails.recorder import Recorder
from ffdetails.store import RecordStore

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


QB_DIRECTORY = """
<script>
var ecrData = {"year":"2026","week":"3","position_id":"QB","scoring":"STD","type":"Weekly","players":[]};
var expertGroupsData = {"expert_data":[
  {"id":2,"name":"Hidden","site":"X","in_season_pos_rank":"1","rankings_link":""},
  {"id":9,"name":"Public A","site":"A Site","in_season_pos_rank":"4","rankings_link":"https://www.fantasypros.com/nfl/rankings/public-a.php?type=weekly&scoring=STD&position=QB"},
  {"id":3,"name":"Public B","site":"B Site","in_season_pos_rank":"2","rankings_link":"/nfl/rankings/public-b.php?type=weekly&scoring=STD&position=QB"},
  {"id":4,"name":"No Rank","site":"C","in_season_pos_rank":"","rankings_link":"/nfl/rankings/no-rank.php?position=QB&scoring=STD"}
]};
</script>
"""

RB_DIRECTORY = """
<script>
var ecrData = {"year":"2026","week":"3","position_id":"RB","scoring":"HALF","type":"Weekly Half PPR","players":[]};
var expertGroupsData = {"expert_data":[
  {"id":8,"name":"RB One","site":"RB Site","in_season_pos_rank":"3","rankings_link":"https://www.fantasypros.com/nfl/rankings/rb-one.php?type=weekly&scoring=HALF&position=RB"},
  {"id":1,"name":"RB Tied","site":"Other","in_season_pos_rank":"3","rankings_link":"https://www.fantasypros.com/nfl/rankings/rb-tied.php?position=RB&scoring=HALF"}
]};
</script>
"""

BOARD_HTML = """
<option value="/nfl/rankings/public-b.php?week=3&amp;position=QB&amp;scoring=STD" selected="selected">Week 3</option>
<table id="data">
<tbody>
<tr>
<td class="center">1</td>
<td class="player-label"><a class="fp-player-link fp-id-17298" fp-player-name="Josh Allen">Josh Allen</a></td>
<td class="center">BUF</td>
<td class="center"> vs.  LAC</td>
<td class="center">1</td>
<td class="center">0</td>
</tr>
<tr>
<td>2</td>
<td><a class="fp-id-19797" fp-player-name="Brock Purdy">Brock Purdy</a></td>
<td>SF</td>
<td>vs. ARI</td>
<td></td>
<td>+1</td>
</tr>
</tbody>
</table>
<table id="other"><tr><td>9</td><td><a class="fp-id-1" fp-player-name="Ignore">Ignore</a></td><td>X</td><td>Y</td><td>1</td></tr></table>
"""


def _expert(**overrides: object) -> FantasyProsExpert:
    payload = dict(
        season=2026,
        week=3,
        position="QB",
        scoring="STD",
        expert_id="3",
        name="Public B",
        site="B Site",
        accuracy_rank=2,
        rankings_url="https://www.fantasypros.com/nfl/rankings/public-b.php?week=3",
        recorded_at=STAMP,
    )
    payload.update(overrides)
    return FantasyProsExpert(**payload)  # type: ignore[arg-type]


class FantasyProsRankTests(unittest.TestCase):
    def test_rank_urls_keep_qb_k_and_dst_on_standard(self) -> None:
        self.assertEqual(
            rankings_url("QB", 3, "HALF"),
            "https://www.fantasypros.com/nfl/rankings/qb.php?week=3",
        )
        self.assertEqual(
            rankings_url("RB", 3, "HALF"),
            "https://www.fantasypros.com/nfl/rankings/half-point-ppr-rb.php?week=3",
        )
        self.assertEqual(
            rankings_url("WR", 3, "PPR"),
            "https://www.fantasypros.com/nfl/rankings/ppr-wr.php?week=3",
        )
        self.assertEqual(
            rankings_url("K", 3, "PPR"),
            "https://www.fantasypros.com/nfl/rankings/k.php?week=3",
        )

    def test_directory_keeps_experts_without_a_public_board(self) -> None:
        experts = parse_rank_experts(
            QB_DIRECTORY, season=2026, week=3, position="QB", scoring="STD", recorded_at=STAMP
        )
        self.assertEqual([expert.expert_id for expert in experts], ["2", "9", "3", "4"])
        hidden = experts[0]
        self.assertIsNone(hidden.rankings_url)
        self.assertEqual(hidden.accuracy_rank, 1)
        chosen = choose_positional_experts(experts, positions=("QB",))
        self.assertEqual(chosen[0].expert_id, "3")
        self.assertEqual(chosen[0].name, "Public B")
        self.assertEqual(
            chosen[0].rankings_url,
            "https://www.fantasypros.com/nfl/rankings/public-b.php?type=weekly&scoring=STD&position=QB&week=3",
        )

    def test_equal_accuracy_keeps_the_lower_expert_id(self) -> None:
        experts = parse_rank_experts(
            RB_DIRECTORY, season=2026, week=3, position="RB", scoring="HALF", recorded_at=STAMP
        )
        chosen = choose_positional_experts(experts)
        self.assertEqual([expert.expert_id for expert in chosen], ["1"])

    def test_missing_public_board_raises(self) -> None:
        experts = parse_rank_experts(
            QB_DIRECTORY, season=2026, week=3, position="QB", scoring="STD", recorded_at=STAMP
        )
        blocked = [
            FantasyProsExpert(
                season=expert.season,
                week=expert.week,
                position=expert.position,
                scoring=expert.scoring,
                expert_id=expert.expert_id,
                name=expert.name,
                site=expert.site,
                accuracy_rank=expert.accuracy_rank,
                rankings_url=None,
                recorded_at=expert.recorded_at,
            )
            for expert in experts
        ]
        with self.assertRaises(ParseError):
            choose_positional_experts(blocked, positions=("QB",))

    def test_board_rows_use_the_expert_table(self) -> None:
        expert = _expert()
        ranks = parse_expert_ranks(BOARD_HTML, expert=expert)
        self.assertEqual([rank.player_id for rank in ranks], ["17298", "19797"])
        self.assertEqual(ranks[0].rank, 1)
        self.assertEqual(ranks[0].team, "BUF")
        self.assertEqual(ranks[0].opponent, "vs. LAC")
        self.assertEqual(ranks[0].ecr, 1)
        self.assertEqual(ranks[0].expert_name, "Public B")
        self.assertEqual(ranks[0].accuracy_rank, 2)
        self.assertIsNone(ranks[1].ecr)
        self.assertEqual(ranks[1].name, "Brock Purdy")

    def test_wrong_week_board_raises(self) -> None:
        html = BOARD_HTML.replace("week=3", "week=2")
        with self.assertRaises(ParseError):
            parse_expert_ranks(html, expert=_expert())

    def test_hybrid_board_keeps_std_positions_when_scoring_is_half(self) -> None:
        qb = _expert()
        rb = _expert(
            position="RB",
            scoring="HALF",
            expert_id="1",
            name="RB Tied",
            accuracy_rank=3,
        )
        std_rb = _expert(
            position="RB",
            scoring="STD",
            expert_id="99",
            name="Standard RB",
            accuracy_rank=1,
        )
        purdy = FantasyProsRank(
            season=2026,
            week=3,
            position="QB",
            scoring="STD",
            expert_id="3",
            expert_name="Public B",
            accuracy_rank=2,
            player_id="19797",
            name="Brock Purdy",
            team="SF",
            opponent="vs. ARI",
            rank=4,
            ecr=4,
            recorded_at=STAMP,
        )
        cmc = FantasyProsRank(
            season=2026,
            week=3,
            position="RB",
            scoring="HALF",
            expert_id="1",
            expert_name="RB Tied",
            accuracy_rank=3,
            player_id="4034",
            name="Christian McCaffrey",
            team="SF",
            opponent="vs. ARI",
            rank=2,
            ecr=1,
            recorded_at=STAMP,
        )
        other = FantasyProsRank(
            season=2026,
            week=3,
            position="RB",
            scoring="STD",
            expert_id="99",
            expert_name="Standard RB",
            accuracy_rank=1,
            player_id="4034",
            name="Christian McCaffrey",
            team="SF",
            opponent=None,
            rank=9,
            ecr=1,
            recorded_at=STAMP,
        )
        board = hybrid_board([qb, rb, std_rb], [other, purdy, cmc], scoring="HALF")
        self.assertEqual([(rank.position, rank.expert_id, rank.rank) for rank in board], [("QB", "3", 4), ("RB", "1", 2)])

    def test_recorder_stores_the_directory_and_the_chosen_board(self) -> None:
        class MapClient:
            def __init__(self) -> None:
                self.urls: list[str] = []

            def get_json(self, url: str) -> object:
                raise AssertionError(url)

            def get_text(self, url: str) -> str:
                self.urls.append(url)
                if url.endswith("qb.php?week=3"):
                    return QB_DIRECTORY
                if "public-b.php" in url:
                    return BOARD_HTML
                raise AssertionError(url)

        client = MapClient()
        store = RecordStore()
        recorder = Recorder(store, fantasypros=type(self)._source(client))
        ranks = recorder.record_fantasypros_ranks(2026, 3, positions=("QB",), recorded_at=STAMP)
        self.assertEqual(len(ranks), 2)
        self.assertEqual(store.fantasypros_experts(2026, 3)[2].expert_id, "3")
        self.assertEqual(store.fantasypros_ranks(2026, 3)[0].name, "Josh Allen")
        self.assertEqual(len(client.urls), 2)
        store.close()

    @staticmethod
    def _source(client: object):
        from ffdetails.fantasypros import FantasyProsSource

        return FantasyProsSource(client)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
