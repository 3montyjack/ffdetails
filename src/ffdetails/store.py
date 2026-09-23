"""SQLite log of recorded details.

Each write appends a snapshot. Reads return the latest snapshot for each
natural key unless history is requested.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ffdetails.records import (
    FantasyProsExpert,
    FantasyProsProjection,
    FantasyProsRank,
    InjuryTag,
    SleeperActual,
    SleeperProjection,
    WaiverBid,
    freeze_stats,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sleeper_actuals (
    id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    player_id TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sleeper_projections (
    id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    season_type TEXT NOT NULL,
    player_id TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fantasypros_projections (
    id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER,
    position TEXT NOT NULL,
    player_id TEXT NOT NULL,
    name TEXT NOT NULL,
    team TEXT,
    scoring TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS injury_tags (
    id INTEGER PRIMARY KEY,
    player_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    name TEXT,
    team TEXT,
    position TEXT,
    body_part TEXT,
    notes TEXT,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS waiver_bids (
    id INTEGER PRIMARY KEY,
    league_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    transaction_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    roster_id INTEGER NOT NULL,
    bid INTEGER NOT NULL,
    status TEXT NOT NULL,
    drops_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fantasypros_experts (
    id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    position TEXT NOT NULL,
    scoring TEXT NOT NULL,
    expert_id TEXT NOT NULL,
    name TEXT NOT NULL,
    site TEXT,
    accuracy_rank INTEGER,
    rankings_url TEXT,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fantasypros_ranks (
    id INTEGER PRIMARY KEY,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    position TEXT NOT NULL,
    scoring TEXT NOT NULL,
    expert_id TEXT NOT NULL,
    expert_name TEXT NOT NULL,
    accuracy_rank INTEGER NOT NULL,
    player_id TEXT NOT NULL,
    name TEXT NOT NULL,
    team TEXT,
    opponent TEXT,
    rank INTEGER NOT NULL,
    ecr INTEGER,
    recorded_at TEXT NOT NULL
);
"""


class RecordStore:
    """Append-only store for recorded details."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('version', '1') "
            "ON CONFLICT(key) DO NOTHING"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> RecordStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def add_sleeper_actuals(self, records: Iterable[SleeperActual]) -> None:
        rows = [
            (
                record.season,
                record.week,
                record.season_type,
                record.player_id,
                _dump_stats(record.stats),
                _stamp(record.recorded_at),
            )
            for record in records
        ]
        self._insert(
            "INSERT INTO sleeper_actuals "
            "(season, week, season_type, player_id, stats_json, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def add_sleeper_projections(self, records: Iterable[SleeperProjection]) -> None:
        rows = [
            (
                record.season,
                record.week,
                record.season_type,
                record.player_id,
                _dump_stats(record.stats),
                _stamp(record.recorded_at),
            )
            for record in records
        ]
        self._insert(
            "INSERT INTO sleeper_projections "
            "(season, week, season_type, player_id, stats_json, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    def add_fantasypros_projections(self, records: Iterable[FantasyProsProjection]) -> None:
        rows = [
            (
                record.season,
                record.week,
                record.position,
                record.player_id,
                record.name,
                record.team,
                record.scoring,
                _dump_stats(record.stats),
                _stamp(record.recorded_at),
            )
            for record in records
        ]
        self._insert(
            "INSERT INTO fantasypros_projections "
            "(season, week, position, player_id, name, team, scoring, stats_json, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def add_fantasypros_experts(self, records: Iterable[FantasyProsExpert]) -> None:
        rows = [
            (
                record.season,
                record.week,
                record.position,
                record.scoring,
                record.expert_id,
                record.name,
                record.site,
                record.accuracy_rank,
                record.rankings_url,
                _stamp(record.recorded_at),
            )
            for record in records
        ]
        self._insert(
            "INSERT INTO fantasypros_experts "
            "(season, week, position, scoring, expert_id, name, site, accuracy_rank, "
            "rankings_url, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def add_fantasypros_ranks(self, records: Iterable[FantasyProsRank]) -> None:
        rows = [
            (
                record.season,
                record.week,
                record.position,
                record.scoring,
                record.expert_id,
                record.expert_name,
                record.accuracy_rank,
                record.player_id,
                record.name,
                record.team,
                record.opponent,
                record.rank,
                record.ecr,
                _stamp(record.recorded_at),
            )
            for record in records
        ]
        self._insert(
            "INSERT INTO fantasypros_ranks "
            "(season, week, position, scoring, expert_id, expert_name, accuracy_rank, "
            "player_id, name, team, opponent, rank, ecr, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def add_injury_tags(self, records: Iterable[InjuryTag]) -> None:
        rows = [
            (
                record.player_id,
                record.tag,
                record.name,
                record.team,
                record.position,
                record.body_part,
                record.notes,
                _stamp(record.recorded_at),
            )
            for record in records
        ]
        self._insert(
            "INSERT INTO injury_tags "
            "(player_id, tag, name, team, position, body_part, notes, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def add_waiver_bids(self, records: Iterable[WaiverBid]) -> None:
        rows = [
            (
                record.league_id,
                record.season,
                record.week,
                record.transaction_id,
                record.player_id,
                record.roster_id,
                record.bid,
                record.status,
                json.dumps(list(record.drops)),
                _stamp(record.recorded_at),
            )
            for record in records
        ]
        self._insert(
            "INSERT INTO waiver_bids "
            "(league_id, season, week, transaction_id, player_id, roster_id, bid, status, "
            "drops_json, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    def sleeper_actuals(
        self,
        season: int,
        week: int,
        *,
        season_type: str = "regular",
        history: bool = False,
    ) -> list[SleeperActual]:
        sql = (
            "SELECT season, week, season_type, player_id, stats_json, recorded_at, id "
            "FROM sleeper_actuals WHERE season = ? AND week = ? AND season_type = ?"
        )
        params: list[Any] = [season, week, season_type]
        rows = self._select(sql, params, history=history, group=("player_id",))
        return [
            SleeperActual(
                season=row["season"],
                week=row["week"],
                season_type=row["season_type"],
                player_id=row["player_id"],
                stats=freeze_stats(_load_stats(row["stats_json"])),
                recorded_at=_parse_stamp(row["recorded_at"]),
            )
            for row in rows
        ]

    def sleeper_projections(
        self,
        season: int,
        week: int,
        *,
        season_type: str = "regular",
        history: bool = False,
    ) -> list[SleeperProjection]:
        sql = (
            "SELECT season, week, season_type, player_id, stats_json, recorded_at, id "
            "FROM sleeper_projections WHERE season = ? AND week = ? AND season_type = ?"
        )
        rows = self._select(
            sql, [season, week, season_type], history=history, group=("player_id",)
        )
        return [
            SleeperProjection(
                season=row["season"],
                week=row["week"],
                season_type=row["season_type"],
                player_id=row["player_id"],
                stats=freeze_stats(_load_stats(row["stats_json"])),
                recorded_at=_parse_stamp(row["recorded_at"]),
            )
            for row in rows
        ]

    def fantasypros_projections(
        self,
        season: int,
        week: int | None,
        *,
        scoring: str = "HALF",
        position: str | None = None,
        history: bool = False,
    ) -> list[FantasyProsProjection]:
        clauses = ["season = ?", "scoring = ?"]
        params: list[Any] = [season, scoring]
        if week is None:
            clauses.append("week IS NULL")
        else:
            clauses.append("week = ?")
            params.append(week)
        if position is not None:
            clauses.append("position = ?")
            params.append(position)
        sql = (
            "SELECT season, week, position, player_id, name, team, scoring, stats_json, "
            "recorded_at, id FROM fantasypros_projections WHERE " + " AND ".join(clauses)
        )
        rows = self._select(sql, params, history=history, group=("position", "player_id"))
        return [
            FantasyProsProjection(
                season=row["season"],
                week=row["week"],
                position=row["position"],
                player_id=row["player_id"],
                name=row["name"],
                team=row["team"],
                scoring=row["scoring"],
                stats=freeze_stats(_load_stats(row["stats_json"])),
                recorded_at=_parse_stamp(row["recorded_at"]),
            )
            for row in rows
        ]

    def fantasypros_experts(
        self,
        season: int,
        week: int,
        *,
        position: str | None = None,
        scoring: str | None = None,
        history: bool = False,
    ) -> list[FantasyProsExpert]:
        clauses = ["season = ?", "week = ?"]
        params: list[Any] = [season, week]
        if position is not None:
            clauses.append("position = ?")
            params.append(position)
        if scoring is not None:
            clauses.append("scoring = ?")
            params.append(scoring)
        sql = (
            "SELECT season, week, position, scoring, expert_id, name, site, accuracy_rank, "
            "rankings_url, recorded_at, id FROM fantasypros_experts WHERE "
            + " AND ".join(clauses)
        )
        rows = self._select(
            sql, params, history=history, group=("position", "scoring", "expert_id")
        )
        return [
            FantasyProsExpert(
                season=row["season"],
                week=row["week"],
                position=row["position"],
                scoring=row["scoring"],
                expert_id=row["expert_id"],
                name=row["name"],
                site=row["site"],
                accuracy_rank=row["accuracy_rank"],
                rankings_url=row["rankings_url"],
                recorded_at=_parse_stamp(row["recorded_at"]),
            )
            for row in rows
        ]

    def fantasypros_ranks(
        self,
        season: int,
        week: int,
        *,
        position: str | None = None,
        scoring: str | None = None,
        history: bool = False,
    ) -> list[FantasyProsRank]:
        clauses = ["season = ?", "week = ?"]
        params: list[Any] = [season, week]
        if position is not None:
            clauses.append("position = ?")
            params.append(position)
        if scoring is not None:
            clauses.append("scoring = ?")
            params.append(scoring)
        sql = (
            "SELECT season, week, position, scoring, expert_id, expert_name, accuracy_rank, "
            "player_id, name, team, opponent, rank, ecr, recorded_at, id "
            "FROM fantasypros_ranks WHERE " + " AND ".join(clauses)
        )
        rows = self._select(
            sql,
            params,
            history=history,
            group=("position", "scoring", "expert_id", "player_id"),
        )
        return [
            FantasyProsRank(
                season=row["season"],
                week=row["week"],
                position=row["position"],
                scoring=row["scoring"],
                expert_id=row["expert_id"],
                expert_name=row["expert_name"],
                accuracy_rank=row["accuracy_rank"],
                player_id=row["player_id"],
                name=row["name"],
                team=row["team"],
                opponent=row["opponent"],
                rank=row["rank"],
                ecr=row["ecr"],
                recorded_at=_parse_stamp(row["recorded_at"]),
            )
            for row in rows
        ]

    def injury_tags(self, *, history: bool = False) -> list[InjuryTag]:
        sql = (
            "SELECT player_id, tag, name, team, position, body_part, notes, recorded_at, id "
            "FROM injury_tags"
        )
        rows = self._select(sql, [], history=history, group=("player_id",))
        return [
            InjuryTag(
                player_id=row["player_id"],
                tag=row["tag"],
                name=row["name"],
                team=row["team"],
                position=row["position"],
                body_part=row["body_part"],
                notes=row["notes"],
                recorded_at=_parse_stamp(row["recorded_at"]),
            )
            for row in rows
        ]

    def waiver_bids(
        self,
        league_id: str,
        season: int,
        week: int,
        *,
        history: bool = False,
    ) -> list[WaiverBid]:
        sql = (
            "SELECT league_id, season, week, transaction_id, player_id, roster_id, bid, "
            "status, drops_json, recorded_at, id FROM waiver_bids "
            "WHERE league_id = ? AND season = ? AND week = ?"
        )
        rows = self._select(
            sql,
            [league_id, season, week],
            history=history,
            group=("transaction_id", "player_id"),
        )
        return [
            WaiverBid(
                league_id=row["league_id"],
                season=row["season"],
                week=row["week"],
                transaction_id=row["transaction_id"],
                player_id=row["player_id"],
                roster_id=row["roster_id"],
                bid=row["bid"],
                status=row["status"],
                drops=tuple(json.loads(row["drops_json"])),
                recorded_at=_parse_stamp(row["recorded_at"]),
            )
            for row in rows
        ]

    def _insert(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        with self._conn:
            self._conn.executemany(sql, rows)

    def _select(
        self,
        sql: str,
        params: list[Any],
        *,
        history: bool,
        group: tuple[str, ...],
    ) -> list[sqlite3.Row]:
        if history:
            order = sql + " ORDER BY recorded_at, id"
            return list(self._conn.execute(order, params))
        group_sql = ", ".join(group)
        latest = (
            f"SELECT MAX(id) AS id FROM ({sql}) AS matched GROUP BY {group_sql}"
        )
        wrapped = (
            f"SELECT matched.* FROM ({sql}) AS matched "
            f"JOIN ({latest}) AS latest ON matched.id = latest.id "
            "ORDER BY matched.id"
        )
        return list(self._conn.execute(wrapped, params + params))


def _dump_stats(stats: Any) -> str:
    return json.dumps(dict(stats), sort_keys=True, separators=(",", ":"))


def _load_stats(payload: str) -> dict[str, int | float]:
    loaded = json.loads(payload)
    stats: dict[str, int | float] = {}
    for key, value in loaded.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        stats[str(key)] = value
    return stats


def _stamp(value: datetime) -> str:
    return value.isoformat()


def _parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value)
