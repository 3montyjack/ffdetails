# ffdetails

`ffdetails` records published fantasy-football datasets:

- Sleeper weekly actuals
- Sleeper weekly projections
- FantasyPros consensus projections
- FantasyPros weekly ranks from the public expert boards worth comparing
- FantasyPros accuracy, season to date and week by week
- Sleeper injury tags
- Sleeper waiver claim bids

Each pull is appended to a sqlite file as a snapshot. A later pull keeps the earlier snapshot in history. Reads return the latest snapshot for each player, claim, or tag.

Lineup choices and waiver bid amounts stay with the caller. This package stores the figures those sources publish.

## Install

```bash
pip install -e .
```

The library uses the Python standard library only.

## Record

```bash
ffdetails sleeper-actuals --season 2026 --week 1
ffdetails sleeper-projections --season 2026 --week 3
ffdetails fantasypros-projections --season 2026 --week 3 --scoring HALF
ffdetails fantasypros-projections --season 2026 --season-long --scoring PPR
ffdetails fantasypros-accuracy --season 2026 --through-week 2
ffdetails fantasypros-ranks --season 2026 --week 3 --scoring HALF --through-week 2 --per-position 3
ffdetails injury-tags
ffdetails waiver-bids --league-id LEAGUE_ID --season 2026 --week 3
ffdetails stat-model --out AGENT_STAT.md
```

`stat-model` fits a half-PPR model from closing moneylines and the weekly injury report, then writes `AGENT_STAT.md`. It does not read Sleeper stats. The moneyline sets the margin, the total on that same board sets the point level, and each injury status scales a player's pre-week mean. The note records how far those estimates landed from the holdout.

Snapshots append to `ffdetails.sqlite` in the current directory. `--db` selects another file.

Sleeper stat maps keep the field names Sleeper publishes, including `pts_ppr`, `pts_half_ppr`, and `pts_std` when they are present. Team-level `TEAM_*` rows are left out. Injury tags are the `injury_status` labels Sleeper publishes, along with body part and notes.

A waiver bid is the integer `settings.waiver_bid` on a Sleeper waiver transaction. When one claim adds more than one player, each added player is stored with that same claim amount. Failed and zero-dollar claims are stored with the status Sleeper published.

FantasyPros consensus pages are read as HTML. The recorder stores every player row in that table, in the order published. The anonymous page currently returns a short public table ahead of a registration module, so an anonymous pull records those public rows. The default scoring view is half-PPR (`HALF`). `STD` and `PPR` select the other published views. Week is a regular-season week, or `--season-long` for the draft-week season table. Season tables also store `bye`. Counting stats use these names:

| Position | Stats |
| --- | --- |
| QB | pass_att, pass_cmp, pass_yd, pass_td, pass_int, rush_att, rush_yd, rush_td, fum_lost, fpts |
| RB | rush_att, rush_yd, rush_td, rec, rec_yd, rec_td, fum_lost, fpts |
| WR | rec, rec_yd, rec_td, rush_att, rush_yd, rush_td, fum_lost, fpts |
| TE | rec, rec_yd, rec_td, fum_lost, fpts |
| K | fg, fga, xpt, fpts |
| DST | sack, int, fum_rec, fum_force, td, safety, pts_allowed, yds_allowed, fpts |

`fpts` is the fantasy-point column on that page. When the page includes a more precise sort value, that value is stored.

`fantasypros-accuracy` records the public accuracy report. With no week, that is season to date. `--week 2` is one completed week. `--through-week 2` records the season and each published week through week 2, and stops when FantasyPros has not published a later week. The anonymous report is a short overall list. Each row has an overall rank and a positional rank. A positional rank above 1 means the leader at that position is outside the published list.

`fantasypros-ranks` records the expert directory and the public boards used to compare sources. The directory is every ranker listed for that position, including in-season positional accuracy and the public board URL when FantasyPros publishes one. `--through-week` records the accuracy windows above and keeps every window leader who still publishes a board. `--per-position` fills any remaining slots from the directory, best in-season positional rank first. The default is one board, the best public in-season ranker. Equal accuracy ranks keep the lower expert id. Experts without a public board stay in the directory and in the accuracy rows, and they are left out of the rank rows.

RB, WR, and TE follow `--scoring` (`HALF` by default, or `STD` / `PPR`). QB, K, and DST stay on the standard board, because FantasyPros publishes those positions once. `hybrid_board` still returns that single best public board. `positional_sources` is the week-by-week leader list, including leaders with no public board. `rank_spreads` lines each player up across the boards that were recorded.

## Library

```python
from ffdetails import RecordStore, Recorder, hybrid_board, positional_sources, rank_spreads

with RecordStore("ffdetails.sqlite") as store:
    recorder = Recorder(store)
    recorder.record_sleeper_actuals(2026, 1)
    recorder.record_fantasypros_ranks(2026, 3, per_position=3, through_week=2)
    latest = store.sleeper_actuals(2026, 1)
    history = store.sleeper_actuals(2026, 1, history=True)
    experts = store.fantasypros_experts(2026, 3)
    ranks = store.fantasypros_ranks(2026, 3)
    board = hybrid_board(experts, ranks)
    sources = positional_sources(store.fantasypros_accuracy(2026, every_window=True), experts)
    spreads = rank_spreads(ranks)
```

`SleeperSource` and `FantasyProsSource` accept any object with `get_json` and `get_text`, so tests can supply saved payloads.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
```
