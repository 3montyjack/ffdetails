# Agent stat model

Pulled Mon Nov 2, 2026 10:09 AM CST.

This model does not read Sleeper stats. Two published inputs are combined:
the moneyline (and the total printed on that same board) and the weekly
injury report. The pre-week projection for a skill player is his own
mean half-PPR in earlier box scores that season. Half-PPR is counted
from play totals: 0.04 per passing yard, 4 per passing touchdown, -1 per
interception, 0.1 per rushing or receiving yard, 6 per rushing or receiving
touchdown, 0.5 per reception, and -2 per fumble lost.

The margin slope is fit on the 2024, 2025 regular season. 2026 is the holdout. A pick'em is forced through a margin of 0.

## Moneyline

Home and away prices are turned into raw probabilities, then divided by
their sum so the vig is removed. The home margin is
`8.46 * log(p / (1 - p))`, where `p` is the no-vig home win
probability. Home points are `(total + margin) / 2` and away points are
`(total - margin) / 2`. The spread is not an input.

Train games: 544. Holdout games: 120.

| Sample | Teams | MAE | RMSE | Bias (predicted - actual) | Correlation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Train | 1088 | 7.15 | 8.92 | -0.66 | 0.431 |
| 2026 | 240 | 7.35 | 9.01 | -0.49 | 0.367 |

On 2026 games, moneyline team points missed the actual
score by 7.35 points per team. The correlation with the
actual score was 0.367.

## Injury report against the pre-week projection

A skill player (QB, RB, WR, TE) enters once his earlier-week mean is at
least 5 half-PPR points and his game has a final score.
Unlisted means he was not Questionable, Doubtful, or Out on that week's
report. The status factor is total points scored divided by total
baseline in the training seasons. The shrink factor is that same ratio
with every status pooled, so the status model has to beat ordinary
regression to the mean.

| Status | Train weeks | Factor | Mean baseline | Mean actual |
| --- | ---: | ---: | ---: | ---: |
| unlisted | 5147 | 0.972 | 11.12 | 10.80 |
| Questionable | 367 | 0.590 | 10.72 | 6.32 |
| Doubtful | 54 | 0.000 | 11.64 | 0.00 |
| Out | 315 | 0.000 | 10.40 | 0.00 |

Holdout counts: unlisted 1004, Questionable 69, Doubtful 2, Out 65.

| Projection | Weeks | MAE | RMSE | Bias | Correlation |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1140 | 6.50 | 8.12 | 1.91 | 0.414 |
| One shrink factor | 1140 | 6.17 | 7.74 | 0.62 | 0.414 |
| Status factor | 1140 | 5.67 | 7.37 | 0.68 | 0.515 |

The pre-week projection misses by 6.50 points. One shrink factor brings that to 6.17 (a 0.33 point gain). Splitting by injury status takes another 0.51 points of MAE off the shrink factor.

Questionable scored 0.590 of the pre-week projection across 367 training weeks. Doubtful scored 0.000 of the pre-week projection across 54 training weeks. Out scored 0.000 of the pre-week projection across 315 training weeks.

## Week 9 posted moneylines

Prices below are the current DraftKings moneylines on the ESPN
scoreboard. Expected points use the slope above and the total on
that board. Kickoffs are CST.

| Kickoff | Game | Moneyline | Total | Expected points |
| --- | --- | --- | ---: | --- |
| Thu Nov 5, 7:15 PM CST | JAX at BAL | JAX -425, BAL +330 | 43.5 | JAX 27.0, BAL 16.5 |
| Sun Nov 8, 8:30 AM CST | CIN at ATL | CIN -166, ATL +140 | 51.5 | CIN 27.5, ATL 24.0 |
| Sun Nov 8, 12:00 PM CST | DEN at CAR | DEN -148, CAR +124 | 43.5 | DEN 23.0, CAR 20.5 |
| Sun Nov 8, 12:00 PM CST | DAL at IND | DAL -258, IND +210 | 51.5 | DAL 29.2, IND 22.3 |
| Sun Nov 8, 12:00 PM CST | NYJ at KC | KC -500, NYJ +380 | 46.5 | NYJ 17.4, KC 29.1 |
| Sun Nov 8, 12:00 PM CST | DET at MIA | DET -375, MIA +295 | 49.5 | DET 29.6, MIA 19.9 |
| Sun Nov 8, 12:00 PM CST | CLE at NO | NO -135, CLE +114 | 43.5 | CLE 20.9, NO 22.6 |
| Sun Nov 8, 12:00 PM CST | NYG at PHI | NYG -166, PHI +140 | 40.5 | NYG 22.0, PHI 18.5 |
| Sun Nov 8, 12:00 PM CST | LAR at WSH | LAR -218, WSH +180 | 47.5 | LAR 26.5, WSH 21.0 |
| Sun Nov 8, 3:05 PM CST | HOU at LAC | HOU -218, LAC +180 | 41.5 | HOU 23.5, LAC 18.0 |
| Sun Nov 8, 3:25 PM CST | GB at NE | NE -148, GB +124 | 46.5 | GB 22.0, NE 24.5 |
| Sun Nov 8, 3:25 PM CST | ARI at SEA | SEA -700, ARI +500 | 44.5 | ARI 15.2, SEA 29.3 |
| Sun Nov 8, 3:25 PM CST | LV at SF | SF -500, LV +380 | 51.5 | LV 19.9, SF 31.6 |
| Sun Nov 8, 7:20 PM CST | TB at CHI | CHI -238, TB +195 | 47.5 | TB 20.7, CHI 26.8 |
| Mon Nov 9, 7:15 PM CST | BUF at MIN | BUF -155, MIN +130 | 46.5 | BUF 24.7, MIN 21.8 |

Historical prices used to fit the slope are the closing moneylines
and totals in the nflverse schedule (`away_moneyline`,
`home_moneyline`, `total_line`). Injury statuses are the nflverse
weekly report (`report_status`). Neither file is a Sleeper stat feed.
