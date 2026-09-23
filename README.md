# ffdetails

`ffdetails` records five published fantasy-football datasets:

- Sleeper weekly actuals
- Sleeper weekly projections
- FantasyPros consensus projections
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
ffdetails injury-tags
ffdetails waiver-bids --league-id LEAGUE_ID --season 2026 --week 3
```

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

## Library

```python
from ffdetails import RecordStore, Recorder

with RecordStore("ffdetails.sqlite") as store:
    recorder = Recorder(store)
    recorder.record_sleeper_actuals(2026, 1)
    latest = store.sleeper_actuals(2026, 1)
    history = store.sleeper_actuals(2026, 1, history=True)
```

`SleeperSource` and `FantasyProsSource` accept any object with `get_json` and `get_text`, so tests can supply saved payloads.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests
```
