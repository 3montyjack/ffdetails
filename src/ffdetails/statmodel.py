"""Moneyline and injury model.

The inputs are posted betting prices and the weekly injury report.
Sleeper stat feeds are not read. Player points are counted from
play-by-play totals at half-PPR: 0.04 per passing yard, 4 per passing
touchdown, -1 per interception, 0.1 per rushing or receiving yard, 6 per
rushing or receiving touchdown, 0.5 per reception, and -2 per fumble lost.
Two-point conversions are left out.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ffdetails.errors import ParseError
from ffdetails.http import UrllibClient

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.csv"
)
INJURIES_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "injuries/injuries_{season}.csv"
)
SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
    "?seasontype=2&week={week}&dates={season}"
)

SKILL = ("QB", "RB", "WR", "TE")
GAME_STATUSES = ("Questionable", "Doubtful", "Out")
BASELINE_MIN = 5.0
CHICAGO = ZoneInfo("America/Chicago")
TRAIN_SEASONS = (2024, 2025)
HOLDOUT_SEASON = 2026


@dataclass(frozen=True)
class MoneylineGame:
    """One game with a home moneyline, an away moneyline, and a total."""

    season: int
    week: int
    game_type: str
    away_team: str
    home_team: str
    away_score: float | None
    home_score: float | None
    away_odds: int
    home_odds: int
    total: float
    kickoff: datetime | None = None
    provider: str = "closing line"


@dataclass(frozen=True)
class ErrorStats:
    """Error of predicted values against actual values."""

    n: int
    mae: float
    rmse: float
    bias: float
    correlation: float | None


@dataclass(frozen=True)
class StatusFactor:
    """How a report status scales a pre-week projection."""

    status: str
    n: int
    factor: float
    mean_baseline: float
    mean_actual: float


@dataclass(frozen=True)
class PlayerFit:
    """Holdout error of the pre-week projection before and after the injury report."""

    baseline: ErrorStats
    shrunk: ErrorStats
    status_adjusted: ErrorStats
    train_factors: tuple[StatusFactor, ...]
    holdout_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class TeamFit:
    """Holdout error of moneyline team points."""

    slope: float
    train: ErrorStats
    holdout: ErrorStats


@dataclass(frozen=True)
class StatReport:
    """Fitted model and the week whose posted moneylines are listed."""

    pulled_at: datetime
    train_seasons: tuple[int, ...]
    holdout_season: int
    team: TeamFit
    player: PlayerFit
    board_week: int
    board: tuple[MoneylineGame, ...]
    train_games: int
    holdout_games: int


def american_implied(odds: int) -> float:
    """Convert American odds to a raw implied probability, vig included."""
    if odds == 0:
        raise ParseError("moneyline odds cannot be 0")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)


def remove_vig(home_odds: int, away_odds: int) -> tuple[float, float]:
    """Split a two-way moneyline into home and away probabilities that sum to 1."""
    home = american_implied(home_odds)
    away = american_implied(away_odds)
    total = home + away
    if total <= 0:
        raise ParseError("moneyline probabilities were empty")
    return home / total, away / total


def logit(probability: float) -> float:
    """Log-odds of a probability clipped away from 0 and 1."""
    clipped = min(max(probability, 1e-6), 1.0 - 1e-6)
    return math.log(clipped / (1.0 - clipped))


def parse_american(value: object) -> int:
    """Read an American price from a number or a string such as '+330'."""
    text = str(value).strip().replace("+", "").replace(",", "")
    if text == "":
        raise ParseError("moneyline odds were blank")
    try:
        return int(float(text))
    except ValueError as exc:
        raise ParseError(f"moneyline odds were not a number: {value}") from exc


def half_ppr(row: Mapping[str, str]) -> float:
    """Count one skill-player line at half-PPR from play totals."""

    def num(key: str) -> float:
        raw = (row.get(key) or "").strip()
        if raw == "":
            return 0.0
        return float(raw)

    fumbles = num("fumbles_lost_total")
    return (
        num("passing_yards") * 0.04
        + num("passing_tds") * 4.0
        + num("passing_interceptions") * -1.0
        + num("rushing_yards") * 0.1
        + num("rushing_tds") * 6.0
        + num("receptions") * 0.5
        + num("receiving_yards") * 0.1
        + num("receiving_tds") * 6.0
        + fumbles * -2.0
    )


def fit_margin_slope(games: Sequence[MoneylineGame]) -> float:
    """Fit home margin = slope * logit(no-vig home win probability).

    The line goes through the origin: a pick'em prices a margin of 0.
    """
    numerator = 0.0
    denominator = 0.0
    for game in games:
        if game.home_score is None or game.away_score is None:
            continue
        if game.game_type not in ("REG", "regular"):
            continue
        home_prob, _away_prob = remove_vig(game.home_odds, game.away_odds)
        feature = logit(home_prob)
        margin = game.home_score - game.away_score
        numerator += feature * margin
        denominator += feature * feature
    if denominator == 0:
        raise ParseError("no completed games with moneylines")
    return numerator / denominator


def expected_team_points(
    home_odds: int, away_odds: int, total: float, slope: float
) -> tuple[float, float]:
    """Split a game total with the moneyline.

    The moneyline supplies the margin. The total on the same board supplies
    the point level. Home points and away points are kept at or above 0.
    """
    home_prob, _away_prob = remove_vig(home_odds, away_odds)
    margin = slope * logit(home_prob)
    home_points = max(0.0, (total + margin) / 2.0)
    away_points = max(0.0, (total - margin) / 2.0)
    return home_points, away_points


def error_stats(pairs: Sequence[tuple[float, float]]) -> ErrorStats:
    """Summarize (predicted, actual) pairs."""
    n = len(pairs)
    if n == 0:
        raise ParseError("error stats need at least one pair")
    residuals = [predicted - actual for predicted, actual in pairs]
    mae = sum(abs(item) for item in residuals) / n
    bias = sum(residuals) / n
    rmse = math.sqrt(sum(item * item for item in residuals) / n)
    return ErrorStats(
        n=n,
        mae=mae,
        rmse=rmse,
        bias=bias,
        correlation=_pearson(pairs),
    )


def team_point_pairs(
    games: Sequence[MoneylineGame], slope: float
) -> list[tuple[float, float]]:
    """Predicted and actual points for each team in a completed game."""
    pairs: list[tuple[float, float]] = []
    for game in games:
        if game.home_score is None or game.away_score is None:
            continue
        if game.game_type not in ("REG", "regular"):
            continue
        home_points, away_points = expected_team_points(
            game.home_odds, game.away_odds, game.total, slope
        )
        pairs.append((home_points, game.home_score))
        pairs.append((away_points, game.away_score))
    return pairs


@dataclass(frozen=True)
class _PlayerWeek:
    season: int
    week: int
    player_id: str
    name: str
    position: str
    status: str
    baseline: float
    actual: float


def build_player_weeks(
    stats_rows: Iterable[Mapping[str, str]],
    injury_rows: Iterable[Mapping[str, str]],
    games: Sequence[MoneylineGame],
    *,
    baseline_min: float = BASELINE_MIN,
) -> list[_PlayerWeek]:
    """Build pre-week projections for skill players in finished games."""
    played = _played_index(stats_rows)
    status_of = _status_index(injury_rows)
    names = _player_names(played, injury_rows)
    final_teams = _final_teams(games)
    weeks_for: dict[tuple[int, str], set[int]] = {}
    for season, week, player_id in set(played) | set(status_of):
        weeks_for.setdefault((season, player_id), set()).add(week)
    rows: list[_PlayerWeek] = []
    for (season, player_id), weeks in weeks_for.items():
        history: list[float] = []
        for week in sorted(weeks):
            key = (season, week, player_id)
            info = names.get(key)
            if info is None:
                continue
            name, position, team = info
            if position not in SKILL:
                continue
            game_is_final = (season, week, team) in final_teams
            if history and game_is_final:
                baseline = sum(history) / len(history)
                if baseline >= baseline_min:
                    actual = played[key][2] if key in played else 0.0
                    rows.append(
                        _PlayerWeek(
                            season=season,
                            week=week,
                            player_id=player_id,
                            name=name,
                            position=position,
                            status=status_of.get(key, "unlisted"),
                            baseline=baseline,
                            actual=actual,
                        )
                    )
            if key in played:
                history.append(played[key][2])
    return rows


def fit_status_factors(rows: Sequence[_PlayerWeek]) -> dict[str, float]:
    """Scale each report status by total actual points over total baseline."""
    totals: dict[str, list[float]] = {}
    for row in rows:
        bucket = totals.setdefault(row.status, [0.0, 0.0])
        bucket[0] += row.actual
        bucket[1] += row.baseline
    factors: dict[str, float] = {}
    for status, (actual, baseline) in totals.items():
        if baseline <= 0:
            continue
        factors[status] = actual / baseline
    if not factors:
        raise ParseError("no player weeks to fit injury factors")
    return factors


def status_factor_rows(rows: Sequence[_PlayerWeek]) -> tuple[StatusFactor, ...]:
    """Describe each fitted status with its sample size and means."""
    grouped: dict[str, list[_PlayerWeek]] = {}
    for row in rows:
        grouped.setdefault(row.status, []).append(row)
    factors = fit_status_factors(rows)
    order = ("unlisted",) + GAME_STATUSES
    described: list[StatusFactor] = []
    for status in order:
        sample = grouped.get(status, [])
        if not sample or status not in factors:
            continue
        described.append(
            StatusFactor(
                status=status,
                n=len(sample),
                factor=factors[status],
                mean_baseline=sum(row.baseline for row in sample) / len(sample),
                mean_actual=sum(row.actual for row in sample) / len(sample),
            )
        )
    return tuple(described)


def fit_player_model(
    train_rows: Sequence[_PlayerWeek], holdout_rows: Sequence[_PlayerWeek]
) -> PlayerFit:
    """Compare the raw pre-week projection, one shrink factor, and status factors."""
    if not train_rows or not holdout_rows:
        raise ParseError("player fit needs train and holdout weeks")
    factors = fit_status_factors(train_rows)
    global_factor = sum(row.actual for row in train_rows) / sum(row.baseline for row in train_rows)
    fallback = factors.get("unlisted", global_factor)

    def pairs(scale) -> list[tuple[float, float]]:
        return [(row.baseline * scale(row), row.actual) for row in holdout_rows]

    return PlayerFit(
        baseline=error_stats(pairs(lambda _row: 1.0)),
        shrunk=error_stats(pairs(lambda _row: global_factor)),
        status_adjusted=error_stats(
            pairs(lambda row: factors.get(row.status, fallback))
        ),
        train_factors=status_factor_rows(train_rows),
        holdout_counts=_counts(holdout_rows),
    )


def fit_report(
    games: Sequence[MoneylineGame],
    stats_rows: Iterable[Mapping[str, str]],
    injury_rows: Iterable[Mapping[str, str]],
    board: Sequence[MoneylineGame],
    *,
    train_seasons: Sequence[int] = TRAIN_SEASONS,
    holdout_season: int = HOLDOUT_SEASON,
    pulled_at: datetime | None = None,
    board_week: int,
) -> StatReport:
    """Fit the moneyline slope and the injury factors, then score the holdout."""
    train_games = [game for game in games if game.season in set(train_seasons)]
    holdout_games = [game for game in games if game.season == holdout_season]
    slope = fit_margin_slope(train_games)
    train_pairs = team_point_pairs(train_games, slope)
    holdout_pairs = team_point_pairs(holdout_games, slope)
    if not train_pairs or not holdout_pairs:
        raise ParseError("team fit needs completed games in train and holdout")
    weeks = build_player_weeks(stats_rows, injury_rows, games)
    train_rows = [row for row in weeks if row.season in set(train_seasons)]
    holdout_rows = [row for row in weeks if row.season == holdout_season]
    stamp = pulled_at or datetime.now(CHICAGO)
    return StatReport(
        pulled_at=stamp.astimezone(CHICAGO),
        train_seasons=tuple(train_seasons),
        holdout_season=holdout_season,
        team=TeamFit(
            slope=slope,
            train=error_stats(train_pairs),
            holdout=error_stats(holdout_pairs),
        ),
        player=fit_player_model(train_rows, holdout_rows),
        board_week=board_week,
        board=tuple(board),
        train_games=len(train_pairs) // 2,
        holdout_games=len(holdout_pairs) // 2,
    )


def render_stat_markdown(report: StatReport) -> str:
    """Write the fitted model in the form the agent reads."""
    team = report.team
    player = report.player
    pulled = report.pulled_at.strftime("%a %b %-d, %Y %-I:%M %p CST")
    train = ", ".join(str(season) for season in report.train_seasons)
    lines = [
        "# Agent stat model",
        "",
        f"Pulled {pulled}.",
        "",
        "This model does not read Sleeper stats. Two published inputs are combined:",
        "the moneyline (and the total printed on that same board) and the weekly",
        "injury report. The pre-week projection for a skill player is his own",
        "mean half-PPR in earlier box scores that season. Half-PPR is counted",
        "from play totals: 0.04 per passing yard, 4 per passing touchdown, -1 per",
        "interception, 0.1 per rushing or receiving yard, 6 per rushing or receiving",
        "touchdown, 0.5 per reception, and -2 per fumble lost.",
        "",
        f"The margin slope is fit on the {train} regular season. "
        f"{report.holdout_season} is the holdout. A pick'em is forced through a margin of 0.",
        "",
        "## Moneyline",
        "",
        "Home and away prices are turned into raw probabilities, then divided by",
        "their sum so the vig is removed. The home margin is",
        f"`{team.slope:.2f} * log(p / (1 - p))`, where `p` is the no-vig home win",
        "probability. Home points are `(total + margin) / 2` and away points are",
        "`(total - margin) / 2`. The spread is not an input.",
        "",
        f"Train games: {report.train_games}. Holdout games: {report.holdout_games}.",
        "",
        "| Sample | Teams | MAE | RMSE | Bias (predicted - actual) | Correlation |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        _error_row("Train", team.train),
        _error_row(str(report.holdout_season), team.holdout),
        "",
        f"On {report.holdout_season} games, moneyline team points missed the actual",
        f"score by {team.holdout.mae:.2f} points per team. The correlation with the",
        f"actual score was {_fmt_corr(team.holdout.correlation)}.",
        "",
        "## Injury report against the pre-week projection",
        "",
        "A skill player (QB, RB, WR, TE) enters once his earlier-week mean is at",
        f"least {BASELINE_MIN:.0f} half-PPR points and his game has a final score.",
        "Unlisted means he was not Questionable, Doubtful, or Out on that week's",
        "report. The status factor is total points scored divided by total",
        "baseline in the training seasons. The shrink factor is that same ratio",
        "with every status pooled, so the status model has to beat ordinary",
        "regression to the mean.",
        "",
        "| Status | Train weeks | Factor | Mean baseline | Mean actual |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for factor in player.train_factors:
        lines.append(
            f"| {factor.status} | {factor.n} | {factor.factor:.3f} | "
            f"{factor.mean_baseline:.2f} | {factor.mean_actual:.2f} |"
        )
    lines.extend(
        [
            "",
            f"Holdout counts: {_count_text(player.holdout_counts)}.",
            "",
            "| Projection | Weeks | MAE | RMSE | Bias | Correlation |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            _error_row("Baseline", player.baseline),
            _error_row("One shrink factor", player.shrunk),
            _error_row("Status factor", player.status_adjusted),
            "",
            _player_closeness(player),
            "",
            _factor_sentence(player.train_factors),
            "",
            f"## Week {report.board_week} posted moneylines",
            "",
            "Prices below are the current DraftKings moneylines on the ESPN",
            "scoreboard. Expected points use the slope above and the total on",
            "that board. Kickoffs are CST.",
            "",
            "| Kickoff | Game | Moneyline | Total | Expected points |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    for game in sorted(report.board, key=lambda item: (item.kickoff or datetime.min.replace(tzinfo=CHICAGO), item.home_team)):
        home_points, away_points = expected_team_points(
            game.home_odds, game.away_odds, game.total, team.slope
        )
        home_prob, away_prob = remove_vig(game.home_odds, game.away_odds)
        favorite, favorite_odds, dog, dog_odds = _favorite(game, home_prob, away_prob)
        kick = format_cst(game.kickoff) if game.kickoff else ""
        lines.append(
            f"| {kick} | {game.away_team} at {game.home_team} | "
            f"{favorite} {format_odds(favorite_odds)}, {dog} {format_odds(dog_odds)} | "
            f"{game.total:.1f} | "
            f"{game.away_team} {away_points:.1f}, {game.home_team} {home_points:.1f} |"
        )
    lines.extend(
        [
            "",
            "Historical prices used to fit the slope are the closing moneylines",
            "and totals in the nflverse schedule (`away_moneyline`,",
            "`home_moneyline`, `total_line`). Injury statuses are the nflverse",
            "weekly report (`report_status`). Neither file is a Sleeper stat feed.",
            "",
        ]
    )
    return "\n".join(lines)


def format_cst(value: datetime) -> str:
    """Format a timestamp in US Central time and label it CST."""
    local = value.astimezone(CHICAGO)
    return local.strftime("%a %b %-d, %-I:%M %p CST")


def format_odds(odds: int) -> str:
    """Format American odds with a leading plus on the underdog price."""
    if odds > 0:
        return f"+{odds}"
    return str(odds)


def parse_games_csv(text: str) -> list[MoneylineGame]:
    """Read closing moneylines from a schedule table."""
    games: list[MoneylineGame] = []
    for row in csv.DictReader(io.StringIO(text)):
        if not row.get("away_moneyline") or not row.get("home_moneyline") or not row.get("total_line"):
            continue
        games.append(
            MoneylineGame(
                season=int(row["season"]),
                week=int(row["week"]),
                game_type=row.get("game_type") or "REG",
                away_team=row["away_team"],
                home_team=row["home_team"],
                away_score=_optional_float(row.get("away_score")),
                home_score=_optional_float(row.get("home_score")),
                away_odds=parse_american(row["away_moneyline"]),
                home_odds=parse_american(row["home_moneyline"]),
                total=float(row["total_line"]),
                provider="closing line",
            )
        )
    return games


def parse_scoreboard(payload: Mapping[str, object], *, season: int, week: int) -> list[MoneylineGame]:
    """Read DraftKings moneylines from an ESPN scoreboard payload."""
    events = payload.get("events") or []
    if not isinstance(events, list):
        raise ParseError("scoreboard events were not a list")
    games: list[MoneylineGame] = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        competitions = event.get("competitions") or []
        if not isinstance(competitions, list) or not competitions:
            continue
        competition = competitions[0]
        if not isinstance(competition, Mapping):
            continue
        odds_list = competition.get("odds") or []
        if not isinstance(odds_list, list) or not odds_list:
            continue
        chosen = _choose_odds(odds_list)
        if chosen is None:
            continue
        home_team, away_team = _scoreboard_teams(competition)
        home_odds = _side_odds(chosen.get("homeTeamOdds"), chosen.get("moneyline"), "home")
        away_odds = _side_odds(chosen.get("awayTeamOdds"), chosen.get("moneyline"), "away")
        total = chosen.get("overUnder")
        if home_team is None or away_team is None or home_odds is None or away_odds is None or total is None:
            continue
        games.append(
            MoneylineGame(
                season=season,
                week=week,
                game_type="REG",
                away_team=away_team,
                home_team=home_team,
                away_score=None,
                home_score=None,
                away_odds=away_odds,
                home_odds=home_odds,
                total=float(total),
                kickoff=_parse_kickoff(competition.get("date") or event.get("date")),
                provider=_provider_name(chosen),
            )
        )
    return games


def load_stat_report(
    http: UrllibClient,
    *,
    train_seasons: Sequence[int] = TRAIN_SEASONS,
    holdout_season: int = HOLDOUT_SEASON,
    pulled_at: datetime | None = None,
) -> StatReport:
    """Download lines, box scores, and injury reports, then fit the model."""
    games = parse_games_csv(http.get_text(GAMES_URL))
    seasons = tuple(train_seasons) + (holdout_season,)
    stats_rows: list[dict[str, str]] = []
    injury_rows: list[dict[str, str]] = []
    for season in seasons:
        stats_rows.extend(
            list(csv.DictReader(io.StringIO(http.get_text(STATS_URL.format(season=season)))))
        )
        injury_rows.extend(
            list(csv.DictReader(io.StringIO(http.get_text(INJURIES_URL.format(season=season)))))
        )
    board_week = _board_week(games, holdout_season)
    board = parse_scoreboard(
        http.get_json(SCOREBOARD_URL.format(week=board_week, season=holdout_season)),
        season=holdout_season,
        week=board_week,
    )
    if not board:
        raise ParseError(f"no moneylines on the week {board_week} scoreboard")
    return fit_report(
        games,
        stats_rows,
        injury_rows,
        board,
        train_seasons=train_seasons,
        holdout_season=holdout_season,
        pulled_at=pulled_at,
        board_week=board_week,
    )


def write_stat_model(http: UrllibClient, path: str, **kwargs: object) -> int:
    """Fit the model and write the agent stat note. Returns the holdout game count."""
    report = load_stat_report(http, **kwargs)  # type: ignore[arg-type]
    text = render_stat_markdown(report)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return report.holdout_games


def _pearson(pairs: Sequence[tuple[float, float]]) -> float | None:
    n = len(pairs)
    if n < 2:
        return None
    predicted = [item[0] for item in pairs]
    actual = [item[1] for item in pairs]
    mean_predicted = sum(predicted) / n
    mean_actual = sum(actual) / n
    covariance = sum(
        (left - mean_predicted) * (right - mean_actual)
        for left, right in zip(predicted, actual)
    )
    scale_predicted = math.sqrt(sum((item - mean_predicted) ** 2 for item in predicted))
    scale_actual = math.sqrt(sum((item - mean_actual) ** 2 for item in actual))
    if scale_predicted == 0 or scale_actual == 0:
        return None
    return covariance / (scale_predicted * scale_actual)


def _played_index(
    rows: Iterable[Mapping[str, str]],
) -> dict[tuple[int, int, str], tuple[str, str, float, str]]:
    index: dict[tuple[int, int, str], tuple[str, str, float, str]] = {}
    for row in rows:
        if (row.get("season_type") or "REG") not in ("REG", "regular"):
            continue
        position = row.get("position") or ""
        player_id = row.get("player_id") or ""
        if player_id == "":
            continue
        name = row.get("player_display_name") or row.get("player_name") or player_id
        index[(int(row["season"]), int(row["week"]), player_id)] = (
            name,
            position,
            half_ppr(row),
            row.get("team") or "",
        )
    return index


def _status_index(rows: Iterable[Mapping[str, str]]) -> dict[tuple[int, int, str], str]:
    rank = {status: index + 1 for index, status in enumerate(GAME_STATUSES)}
    chosen: dict[tuple[int, int, str], tuple[int, str]] = {}
    for row in rows:
        status = (row.get("report_status") or "").strip()
        if status not in rank:
            continue
        player_id = row.get("gsis_id") or row.get("player_id") or ""
        if player_id == "":
            continue
        key = (int(row["season"]), int(row["week"]), player_id)
        current = chosen.get(key)
        if current is None or rank[status] >= current[0]:
            chosen[key] = (rank[status], status)
    return {key: status for key, (_rank, status) in chosen.items()}


def _injury_names(
    rows: Iterable[Mapping[str, str]],
) -> dict[tuple[int, int, str], tuple[str, str, str]]:
    names: dict[tuple[int, int, str], tuple[str, str, str]] = {}
    for row in rows:
        player_id = row.get("gsis_id") or row.get("player_id") or ""
        if player_id == "":
            continue
        key = (int(row["season"]), int(row["week"]), player_id)
        names[key] = (
            row.get("full_name") or player_id,
            row.get("position") or "",
            row.get("team") or "",
        )
    return names


def _player_names(
    played: Mapping[tuple[int, int, str], tuple[str, str, float, str]],
    injury_rows: Iterable[Mapping[str, str]],
) -> dict[tuple[int, int, str], tuple[str, str, str]]:
    """Name, position, and team for a player-week.

    The box score supplies the team when the player played. The injury report
    supplies it when he did not appear.
    """
    names: dict[tuple[int, int, str], tuple[str, str, str]] = {}
    listed = _injury_names(injury_rows)
    for key, (name, position, _points, team) in played.items():
        if team == "" and key in listed:
            team = listed[key][2]
        names[key] = (name, position, team)
    for key, (name, position, team) in listed.items():
        if key not in names:
            names[key] = (name, position, team)
    return names


def _final_teams(games: Sequence[MoneylineGame]) -> set[tuple[int, int, str]]:
    teams: set[tuple[int, int, str]] = set()
    for game in games:
        if game.home_score is None or game.away_score is None:
            continue
        if game.game_type not in ("REG", "regular"):
            continue
        teams.add((game.season, game.week, game.home_team))
        teams.add((game.season, game.week, game.away_team))
    return teams


def _optional_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    return float(value)


def _counts(rows: Sequence[_PlayerWeek]) -> tuple[tuple[str, int], ...]:
    totals: dict[str, int] = {}
    for row in rows:
        totals[row.status] = totals.get(row.status, 0) + 1
    order = ("unlisted",) + GAME_STATUSES
    return tuple((status, totals[status]) for status in order if status in totals)


def _count_text(counts: Sequence[tuple[str, int]]) -> str:
    return ", ".join(f"{status} {count}" for status, count in counts)


def _error_row(label: str, stats: ErrorStats) -> str:
    return (
        f"| {label} | {stats.n} | {stats.mae:.2f} | {stats.rmse:.2f} | "
        f"{stats.bias:.2f} | {_fmt_corr(stats.correlation)} |"
    )


def _fmt_corr(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def _factor_sentence(factors: tuple[StatusFactor, ...]) -> str:
    by_status = {factor.status: factor for factor in factors}
    parts: list[str] = []
    for status in GAME_STATUSES:
        factor = by_status.get(status)
        if factor is None:
            continue
        parts.append(
            f"{status} scored {factor.factor:.3f} of the pre-week projection "
            f"across {factor.n} training weeks"
        )
    if not parts:
        return ""
    return ". ".join(parts) + "."


def _player_closeness(player: PlayerFit) -> str:
    status_gain = player.shrunk.mae - player.status_adjusted.mae
    shrink_gain = player.baseline.mae - player.shrunk.mae
    if status_gain > 0.05:
        extra = (
            f"Splitting by injury status takes another {status_gain:.2f} points of"
            f" MAE off the shrink factor."
        )
    else:
        extra = (
            "Splitting by injury status changes the shrink-factor MAE by"
            f" {status_gain:.2f} points."
        )
    return (
        f"The pre-week projection misses by {player.baseline.mae:.2f} points."
        f" One shrink factor brings that to {player.shrunk.mae:.2f}"
        f" (a {shrink_gain:.2f} point gain). {extra}"
    )


def _favorite(
    game: MoneylineGame, home_prob: float, away_prob: float
) -> tuple[str, int, str, int]:
    if home_prob >= away_prob:
        return game.home_team, game.home_odds, game.away_team, game.away_odds
    return game.away_team, game.away_odds, game.home_team, game.home_odds


def _choose_odds(odds_list: Sequence[object]) -> Mapping[str, object] | None:
    parsed = [item for item in odds_list if isinstance(item, Mapping)]
    for item in parsed:
        if _provider_name(item) == "DraftKings":
            return item
    return parsed[0] if parsed else None


def _provider_name(odds: Mapping[str, object]) -> str:
    provider = odds.get("provider")
    if isinstance(provider, Mapping):
        name = provider.get("displayName") or provider.get("name") or ""
        return str(name)
    return ""


def _scoreboard_teams(competition: Mapping[str, object]) -> tuple[str | None, str | None]:
    home = away = None
    competitors = competition.get("competitors") or []
    if not isinstance(competitors, list):
        return None, None
    for competitor in competitors:
        if not isinstance(competitor, Mapping):
            continue
        team = competitor.get("team")
        abbreviation = ""
        if isinstance(team, Mapping):
            abbreviation = str(team.get("abbreviation") or "")
        side = competitor.get("homeAway")
        if side == "home":
            home = abbreviation
        elif side == "away":
            away = abbreviation
    return home, away


def _side_odds(
    team_odds: object, moneyline: object, side: str
) -> int | None:
    if isinstance(team_odds, Mapping) and team_odds.get("moneyLine") not in (None, ""):
        return parse_american(team_odds["moneyLine"])
    if isinstance(moneyline, Mapping):
        nested = moneyline.get(side)
        if isinstance(nested, Mapping):
            close = nested.get("close")
            if isinstance(close, Mapping) and close.get("odds") not in (None, ""):
                return parse_american(close["odds"])
            if nested.get("odds") not in (None, ""):
                return parse_american(nested["odds"])
    return None


def _parse_kickoff(value: object) -> datetime | None:
    if not isinstance(value, str) or value == "":
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _board_week(games: Sequence[MoneylineGame], season: int) -> int:
    """Pick the next slate that still has a full set of unplayed games."""
    by_week: dict[int, list[MoneylineGame]] = {}
    for game in games:
        if game.season != season or game.game_type not in ("REG", "regular"):
            continue
        by_week.setdefault(game.week, []).append(game)
    for week in sorted(by_week):
        unfinished = [game for game in by_week[week] if game.home_score is None]
        if len(unfinished) >= 8:
            return week
    if by_week:
        return max(by_week)
    raise ParseError(f"no schedule rows for {season}")
