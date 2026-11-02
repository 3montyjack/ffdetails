"""Moneyline and injury math stays independent of Sleeper stat feeds."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ffdetails.statmodel import (
    MoneylineGame,
    american_implied,
    build_player_weeks,
    expected_team_points,
    fit_margin_slope,
    fit_report,
    format_cst,
    half_ppr,
    parse_american,
    parse_games_csv,
    parse_scoreboard,
    remove_vig,
    render_stat_markdown,
)


def game(
    season: int,
    week: int,
    home_odds: int,
    away_odds: int,
    total: float,
    home_score: float | None,
    away_score: float | None,
    home: str = "HOM",
    away: str = "AWY",
) -> MoneylineGame:
    return MoneylineGame(
        season=season,
        week=week,
        game_type="REG",
        away_team=away,
        home_team=home,
        away_score=away_score,
        home_score=home_score,
        away_odds=away_odds,
        home_odds=home_odds,
        total=total,
        kickoff=datetime(2026, 11, 8, 18, tzinfo=timezone.utc),
        provider="DraftKings",
    )


class MoneylineTests(unittest.TestCase):
    def test_american_prices_and_vig_removal(self) -> None:
        self.assertAlmostEqual(american_implied(100), 0.5)
        self.assertAlmostEqual(american_implied(parse_american("+330")), 100 / 430)
        self.assertAlmostEqual(american_implied(-425), 425 / 525)
        home, away = remove_vig(-110, -110)
        self.assertAlmostEqual(home, 0.5)
        self.assertAlmostEqual(away, 0.5)
        self.assertAlmostEqual(home + away, 1)

    def test_pickem_margin_is_zero_and_favorite_takes_more_of_the_total(self) -> None:
        # A home favorite that won by 10, and a pick'em that finished tied.
        # The slope has to be positive because the favorite's log-odds lined up
        # with a positive home margin.
        games = [
            game(2024, 1, -200, 170, 44, 27, 17),
            game(2024, 1, -110, -110, 40, 20, 20),
        ]
        slope = fit_margin_slope(games)
        self.assertGreater(slope, 0)
        home_points, away_points = expected_team_points(-200, 170, 44, slope)
        self.assertGreater(home_points, away_points)
        self.assertAlmostEqual(home_points + away_points, 44, places=5)

    def test_half_ppr_counts_the_play_totals(self) -> None:
        points = half_ppr(
            {
                "passing_yards": "300",
                "passing_tds": "2",
                "passing_interceptions": "1",
                "rushing_yards": "10",
                "rushing_tds": "0",
                "receptions": "0",
                "receiving_yards": "0",
                "receiving_tds": "0",
                "fumbles_lost_total": "0",
            }
        )
        self.assertAlmostEqual(points, 300 * 0.04 + 8 - 1 + 1)

    def test_schedule_csv_keeps_priced_games_only(self) -> None:
        text = (
            "season,game_type,week,away_team,home_team,away_score,home_score,"
            "away_moneyline,home_moneyline,total_line\n"
            "2024,REG,1,AWY,HOM,17,27,170,-200,44\n"
            "2024,REG,2,AWY,HOM,,,,,\n"
        )
        games = parse_games_csv(text)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].home_odds, -200)
        self.assertEqual(games[0].home_score, 27)


class InjuryTests(unittest.TestCase):
    def test_out_scales_the_preweek_projection_down(self) -> None:
        stats = []
        injuries = []
        games = []
        # Two seasons. Player scores 10 when unlisted and 0 when Out.
        for season, week, status, actual in (
            (2024, 1, "unlisted", 10),
            (2024, 2, "Out", 0),
            (2024, 3, "unlisted", 10),
            (2025, 1, "unlisted", 10),
            (2025, 2, "Out", 0),
            (2026, 1, "unlisted", 10),
            (2026, 2, "Out", 0),
            (2026, 3, "unlisted", 10),
        ):
            games.append(game(season, week, -150, 130, 44, 24, 20))
            if status != "unlisted":
                injuries.append(
                    {
                        "season": str(season),
                        "week": str(week),
                        "gsis_id": "p1",
                        "full_name": "Pat Player",
                        "position": "WR",
                        "team": "HOM",
                        "report_status": status,
                    }
                )
            if actual:
                stats.append(
                    {
                        "season": str(season),
                        "week": str(week),
                        "season_type": "REG",
                        "player_id": "p1",
                        "player_display_name": "Pat Player",
                        "position": "WR",
                        "team": "HOM",
                        "receptions": "4",
                        "receiving_yards": "80",
                        "receiving_tds": "0",
                        "fumbles_lost_total": "0",
                    }
                )
        rows = build_player_weeks(stats, injuries, games, baseline_min=5)
        holdout = [row for row in rows if row.season == 2026]
        self.assertTrue(any(row.status == "Out" and row.actual == 0 for row in holdout))
        report = fit_report(
            games,
            stats,
            injuries,
            [game(2026, 9, -150, 130, 45, None, None)],
            train_seasons=(2024, 2025),
            holdout_season=2026,
            pulled_at=datetime(2026, 11, 2, 15, 30, tzinfo=timezone.utc),
            board_week=9,
        )
        factors = {item.status: item.factor for item in report.player.train_factors}
        self.assertLess(factors["Out"], 0.2)
        self.assertLess(report.player.status_adjusted.mae, report.player.baseline.mae)
        text = render_stat_markdown(report)
        self.assertIn("does not read Sleeper stats", text)
        self.assertIn("Out", text)
        self.assertIn("Mon Nov 2, 9:30 AM CST", format_cst(report.pulled_at))
        self.assertIn("Sun Nov 8, 12:00 PM CST", text)


class ScoreboardTests(unittest.TestCase):
    def test_draftkings_moneyline_is_read_from_the_scoreboard(self) -> None:
        payload = {
            "events": [
                {
                    "date": "2026-11-08T18:00Z",
                    "competitions": [
                        {
                            "date": "2026-11-08T18:00Z",
                            "competitors": [
                                {"homeAway": "home", "team": {"abbreviation": "NYG"}},
                                {"homeAway": "away", "team": {"abbreviation": "PHI"}},
                            ],
                            "odds": [
                                {
                                    "provider": {"displayName": "DraftKings"},
                                    "overUnder": 43.5,
                                    "moneyline": {
                                        "home": {"close": {"odds": "+180"}},
                                        "away": {"close": {"odds": "-210"}},
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
        games = parse_scoreboard(payload, season=2026, week=9)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].home_team, "NYG")
        self.assertEqual(games[0].away_odds, -210)
        self.assertEqual(games[0].total, 43.5)
        self.assertEqual(games[0].provider, "DraftKings")


if __name__ == "__main__":
    unittest.main()
