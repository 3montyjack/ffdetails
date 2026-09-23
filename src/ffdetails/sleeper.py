"""Read Sleeper actuals, projections, injury tags, and waiver bids."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from ffdetails.errors import ParseError
from ffdetails.http import UrllibClient
from ffdetails.records import InjuryTag, SleeperActual, SleeperProjection, WaiverBid, freeze_stats
from ffdetails.timeutil import as_utc

SLEEPER_API = "https://api.sleeper.app/v1"
SEASON_TYPES = ("regular", "post", "pre")


class SleeperSource:
    """Fetch published Sleeper details."""

    def __init__(self, http: UrllibClient | None = None) -> None:
        self.http = http or UrllibClient()

    def actuals(
        self,
        season: int,
        week: int,
        *,
        season_type: str = "regular",
        recorded_at: datetime | None = None,
    ) -> list[SleeperActual]:
        payload = self.http.get_json(stats_url(season, week, season_type))
        return parse_actuals(
            payload,
            season=season,
            week=week,
            season_type=season_type,
            recorded_at=as_utc(recorded_at),
        )

    def projections(
        self,
        season: int,
        week: int,
        *,
        season_type: str = "regular",
        recorded_at: datetime | None = None,
    ) -> list[SleeperProjection]:
        payload = self.http.get_json(projections_url(season, week, season_type))
        return parse_projections(
            payload,
            season=season,
            week=week,
            season_type=season_type,
            recorded_at=as_utc(recorded_at),
        )

    def injury_tags(self, *, recorded_at: datetime | None = None) -> list[InjuryTag]:
        payload = self.http.get_json(players_url())
        return parse_injury_tags(payload, recorded_at=as_utc(recorded_at))

    def waiver_bids(
        self,
        league_id: str,
        season: int,
        week: int,
        *,
        recorded_at: datetime | None = None,
    ) -> list[WaiverBid]:
        payload = self.http.get_json(transactions_url(league_id, week))
        return parse_waiver_bids(
            payload,
            league_id=league_id,
            season=season,
            week=week,
            recorded_at=as_utc(recorded_at),
        )


def stats_url(season: int, week: int, season_type: str = "regular") -> str:
    _require_season_week(season, week, season_type)
    return f"{SLEEPER_API}/stats/nfl/{season_type}/{season}/{week}"


def projections_url(season: int, week: int, season_type: str = "regular") -> str:
    _require_season_week(season, week, season_type)
    return f"{SLEEPER_API}/projections/nfl/{season_type}/{season}/{week}"


def players_url() -> str:
    return f"{SLEEPER_API}/players/nfl"


def transactions_url(league_id: str, week: int) -> str:
    league = _require_league_id(league_id)
    if not isinstance(week, int) or isinstance(week, bool) or week < 1:
        raise ParseError("week must be an integer >= 1")
    return f"{SLEEPER_API}/league/{league}/transactions/{week}"


def parse_actuals(
    payload: Any,
    *,
    season: int,
    week: int,
    season_type: str = "regular",
    recorded_at: datetime,
) -> list[SleeperActual]:
    rows = _player_stat_rows(payload)
    stamp = as_utc(recorded_at)
    return [
        SleeperActual(
            season=season,
            week=week,
            player_id=player_id,
            stats=freeze_stats(stats),
            recorded_at=stamp,
            season_type=season_type,
        )
        for player_id, stats in rows
    ]


def parse_projections(
    payload: Any,
    *,
    season: int,
    week: int,
    season_type: str = "regular",
    recorded_at: datetime,
) -> list[SleeperProjection]:
    rows = _player_stat_rows(payload)
    stamp = as_utc(recorded_at)
    return [
        SleeperProjection(
            season=season,
            week=week,
            player_id=player_id,
            stats=freeze_stats(stats),
            recorded_at=stamp,
            season_type=season_type,
        )
        for player_id, stats in rows
    ]


def parse_injury_tags(payload: Any, *, recorded_at: datetime) -> list[InjuryTag]:
    if not isinstance(payload, dict):
        raise ParseError("Sleeper players payload must be an object")
    stamp = as_utc(recorded_at)
    tags: list[InjuryTag] = []
    for key, player in payload.items():
        if not isinstance(player, dict):
            continue
        raw_tag = player.get("injury_status")
        if not isinstance(raw_tag, str) or not raw_tag.strip():
            continue
        player_id = player.get("player_id") or key
        if not isinstance(player_id, str) or not player_id:
            raise ParseError("injury tag is missing a player id")
        tags.append(
            InjuryTag(
                player_id=player_id,
                tag=raw_tag.strip(),
                name=_optional_str(player.get("full_name")),
                team=_optional_str(player.get("team")),
                position=_optional_str(player.get("position")),
                body_part=_optional_str(player.get("injury_body_part")),
                notes=_optional_str(player.get("injury_notes")),
                recorded_at=stamp,
            )
        )
    return tags


def parse_waiver_bids(
    payload: Any,
    *,
    league_id: str,
    season: int,
    week: int,
    recorded_at: datetime,
) -> list[WaiverBid]:
    if not isinstance(payload, list):
        raise ParseError("Sleeper transactions payload must be a list")
    league = _require_league_id(league_id)
    _require_season_week(season, week, "regular")
    stamp = as_utc(recorded_at)
    bids: list[WaiverBid] = []
    for tx in payload:
        if not isinstance(tx, dict) or tx.get("type") != "waiver":
            continue
        settings = tx.get("settings") or {}
        if not isinstance(settings, dict) or "waiver_bid" not in settings:
            continue
        bid = _require_bid(settings.get("waiver_bid"), tx.get("transaction_id"))
        transaction_id = tx.get("transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id:
            raise ParseError("waiver bid is missing a transaction id")
        status = tx.get("status")
        if not isinstance(status, str) or not status:
            raise ParseError(f"waiver bid {transaction_id} is missing a status")
        adds = tx.get("adds")
        if not isinstance(adds, dict) or not adds:
            raise ParseError(f"waiver bid {transaction_id} has no added player")
        drops = _drop_ids(tx.get("drops"))
        for player_id, roster_id in adds.items():
            if not isinstance(player_id, str) or not player_id:
                raise ParseError(f"waiver bid {transaction_id} has an empty player id")
            bids.append(
                WaiverBid(
                    league_id=league,
                    season=season,
                    week=week,
                    transaction_id=transaction_id,
                    player_id=player_id,
                    roster_id=_require_roster_id(roster_id, transaction_id),
                    bid=bid,
                    status=status,
                    drops=drops,
                    recorded_at=stamp,
                )
            )
    return bids


def _player_stat_rows(payload: Any) -> list[tuple[str, dict[str, int | float]]]:
    if not isinstance(payload, dict):
        raise ParseError("Sleeper stat payload must be an object keyed by player id")
    rows: list[tuple[str, dict[str, int | float]]] = []
    for player_id, raw_stats in payload.items():
        if not isinstance(player_id, str) or player_id.startswith("TEAM_"):
            continue
        if not isinstance(raw_stats, dict):
            raise ParseError(f"stats for {player_id} must be an object")
        stats = _numeric_stats(raw_stats)
        if stats:
            rows.append((player_id, stats))
    return rows


def _numeric_stats(raw: Mapping[str, Any]) -> dict[str, int | float]:
    stats: dict[str, int | float] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        stats[str(key)] = value
    return stats


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _require_season_week(season: int, week: int, season_type: str) -> None:
    if not isinstance(season, int) or isinstance(season, bool) or season < 2000:
        raise ParseError("season must be an integer year")
    if not isinstance(week, int) or isinstance(week, bool) or week < 1:
        raise ParseError("week must be an integer >= 1")
    if season_type not in SEASON_TYPES:
        raise ParseError(f"season_type must be one of {', '.join(SEASON_TYPES)}")


def _require_league_id(league_id: str) -> str:
    if not isinstance(league_id, str) or not league_id.strip() or any(ch.isspace() for ch in league_id):
        raise ParseError("league_id must be a non-empty id")
    return league_id.strip()


def _require_bid(value: Any, transaction_id: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParseError(f"waiver bid {transaction_id} is not an integer amount")
    if value < 0:
        raise ParseError(f"waiver bid {transaction_id} is negative")
    return value


def _require_roster_id(value: Any, transaction_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParseError(f"waiver bid {transaction_id} is missing a roster id")
    return value


def _drop_ids(drops: Any) -> tuple[str, ...]:
    if drops is None:
        return ()
    if not isinstance(drops, dict):
        raise ParseError("waiver drops must be an object")
    ids: list[str] = []
    for player_id in drops:
        if not isinstance(player_id, str) or not player_id:
            raise ParseError("waiver drop is missing a player id")
        ids.append(player_id)
    return tuple(ids)
