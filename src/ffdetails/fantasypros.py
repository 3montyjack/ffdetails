"""Read FantasyPros consensus projection tables."""

from __future__ import annotations

import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from ffdetails.errors import ParseError
from ffdetails.http import UrllibClient
from ffdetails.records import FantasyProsProjection, freeze_stats
from ffdetails.timeutil import as_utc

FANTASYPROS_PROJECTIONS = "https://www.fantasypros.com/nfl/projections"
SCORING = ("STD", "HALF", "PPR")
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")

# Weekly column order. Season tables insert bye ahead of these columns.
STAT_KEYS: dict[str, tuple[str, ...]] = {
    "QB": (
        "pass_att",
        "pass_cmp",
        "pass_yd",
        "pass_td",
        "pass_int",
        "rush_att",
        "rush_yd",
        "rush_td",
        "fum_lost",
        "fpts",
    ),
    "RB": ("rush_att", "rush_yd", "rush_td", "rec", "rec_yd", "rec_td", "fum_lost", "fpts"),
    "WR": ("rec", "rec_yd", "rec_td", "rush_att", "rush_yd", "rush_td", "fum_lost", "fpts"),
    "TE": ("rec", "rec_yd", "rec_td", "fum_lost", "fpts"),
    "K": ("fg", "fga", "xpt", "fpts"),
    "DST": (
        "sack",
        "int",
        "fum_rec",
        "fum_force",
        "td",
        "safety",
        "pts_allowed",
        "yds_allowed",
        "fpts",
    ),
}

# (group, column label) -> stored stat name. An empty group is an ungrouped column.
COLUMN_KEYS: dict[tuple[str, str], str] = {
    ("PASSING", "ATT"): "pass_att",
    ("PASSING", "CMP"): "pass_cmp",
    ("PASSING", "YDS"): "pass_yd",
    ("PASSING", "TDS"): "pass_td",
    ("PASSING", "INTS"): "pass_int",
    ("RUSHING", "ATT"): "rush_att",
    ("RUSHING", "YDS"): "rush_yd",
    ("RUSHING", "TDS"): "rush_td",
    ("RECEIVING", "REC"): "rec",
    ("RECEIVING", "YDS"): "rec_yd",
    ("RECEIVING", "TDS"): "rec_td",
    ("MISC", "FL"): "fum_lost",
    ("MISC", "FPTS"): "fpts",
    ("", "BYE"): "bye",
    ("", "FG"): "fg",
    ("", "FGA"): "fga",
    ("", "XPT"): "xpt",
    ("", "FPTS"): "fpts",
    ("", "SACK"): "sack",
    ("", "INT"): "int",
    ("", "FR"): "fum_rec",
    ("", "FF"): "fum_force",
    ("", "TD"): "td",
    ("", "SAFETY"): "safety",
    ("", "PA"): "pts_allowed",
    ("", "YDS AGN"): "yds_allowed",
}

_PLAYER_ID = re.compile(r"fp-id-(\d+)")


class FantasyProsSource:
    """Fetch published FantasyPros consensus projections."""

    def __init__(self, http: UrllibClient | None = None) -> None:
        self.http = http or UrllibClient()

    def projections(
        self,
        season: int,
        week: int | None,
        *,
        positions: tuple[str, ...] | list[str] = POSITIONS,
        scoring: str = "HALF",
        recorded_at: datetime | None = None,
    ) -> list[FantasyProsProjection]:
        stamp = as_utc(recorded_at)
        scoring_name = normalize_scoring(scoring)
        chosen = _normalize_positions(positions)
        records: list[FantasyProsProjection] = []
        for position in chosen:
            html = self.http.get_text(projections_url(position, week, scoring_name))
            records.extend(
                parse_projections(
                    html,
                    season=season,
                    week=week,
                    position=position,
                    scoring=scoring_name,
                    recorded_at=stamp,
                )
            )
        return records


def projections_url(position: str, week: int | None, scoring: str = "HALF") -> str:
    position_name = _normalize_positions((position,))[0]
    scoring_name = normalize_scoring(scoring)
    week_query = "draft" if week is None else _week_query(week)
    slug = position_name.lower()
    return (
        f"{FANTASYPROS_PROJECTIONS}/{slug}.php?week={week_query}&scoring={scoring_name}"
    )


def normalize_scoring(scoring: str) -> str:
    if not isinstance(scoring, str):
        raise ParseError("scoring must be STD, HALF, or PPR")
    name = scoring.strip().upper()
    if name not in SCORING:
        raise ParseError("scoring must be STD, HALF, or PPR")
    return name


def parse_projections(
    html: str,
    *,
    season: int,
    week: int | None,
    position: str,
    scoring: str,
    recorded_at: datetime,
) -> list[FantasyProsProjection]:
    if not isinstance(season, int) or isinstance(season, bool) or season < 2000:
        raise ParseError("season must be an integer year")
    if week is not None:
        _week_query(week)
    position_name = _normalize_positions((position,))[0]
    scoring_name = normalize_scoring(scoring)
    parser = _ProjectionTableParser()
    parser.feed(html)
    parser.close()
    if not parser.saw_tbody:
        raise ParseError(f"FantasyPros {position_name} page has no projection table")
    keys = _keys_from_headers(position_name, parser.header_rows)
    stamp = as_utc(recorded_at)
    records: list[FantasyProsProjection] = []
    for cells in parser.rows:
        record = _row_to_record(
            cells,
            keys=keys,
            season=season,
            week=week,
            position=position_name,
            scoring=scoring_name,
            recorded_at=stamp,
        )
        if record is not None:
            records.append(record)
    if not records:
        raise ParseError(f"FantasyPros {position_name} page has no player rows")
    return records


def _row_to_record(
    cells: list[dict[str, Any]],
    *,
    keys: tuple[str, ...],
    season: int,
    week: int | None,
    position: str,
    scoring: str,
    recorded_at: datetime,
) -> FantasyProsProjection | None:
    if not cells:
        return None
    anchor = cells[0].get("anchor") or {}
    class_name = str(anchor.get("class") or "")
    match = _PLAYER_ID.search(class_name)
    if match is None:
        return None
    name = anchor.get("fp-player-name") or _collapsed(cells[0].get("text") or "")
    if not isinstance(name, str) or not name.strip():
        raise ParseError(f"FantasyPros {position} row is missing a player name")
    name = name.strip()
    team = _team(cells[0].get("text") or "", name)
    values = cells[1:]
    if len(values) != len(keys):
        raise ParseError(
            f"FantasyPros {position} row for {name} has {len(values)} stats, expected {len(keys)}"
        )
    stats = {key: _number(cell, player=name) for key, cell in zip(keys, values)}
    return FantasyProsProjection(
        season=season,
        week=week,
        position=position,
        player_id=match.group(1),
        name=name,
        team=team,
        scoring=scoring,
        stats=freeze_stats(stats),
        recorded_at=recorded_at,
    )


def _number(cell: dict[str, Any], *, player: str) -> float:
    raw = cell.get("sort")
    if raw is None or raw == "":
        raw = cell.get("text")
    if not isinstance(raw, str):
        raise ParseError(f"FantasyPros stat for {player} is missing")
    token = raw.strip().replace(",", "")
    try:
        return float(token)
    except ValueError as exc:
        raise ParseError(f"FantasyPros stat for {player} is not a number: {token!r}") from exc


def _team(cell_text: str, name: str) -> str | None:
    collapsed = _collapsed(cell_text)
    if collapsed == name:
        return None
    if collapsed.startswith(name):
        rest = collapsed[len(name) :].strip()
        return rest or None
    return None


def _collapsed(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _norm_header(text: str) -> str:
    return _collapsed(text).upper()


def _keys_from_headers(position: str, header_rows: list[list[dict[str, Any]]]) -> tuple[str, ...]:
    label_index = None
    for index, row in enumerate(header_rows):
        if row and _norm_header(str(row[0].get("text") or "")) == "PLAYER":
            label_index = index
            break
    if label_index is None:
        raise ParseError(f"FantasyPros {position} page is missing column headers")
    labels = [_norm_header(str(cell.get("text") or "")) for cell in header_rows[label_index][1:]]
    if label_index == 0:
        groups = [""] * len(labels)
    else:
        groups = []
        for cell in header_rows[label_index - 1][1:]:
            span = int(cell.get("colspan") or 1)
            groups.extend([_norm_header(str(cell.get("text") or ""))] * span)
        if len(groups) != len(labels):
            raise ParseError(f"FantasyPros {position} header groups do not match columns")
    keys: list[str] = []
    for group, label in zip(groups, labels):
        key = COLUMN_KEYS.get((group, label))
        if key is None:
            raise ParseError(f"FantasyPros {position} column {label or group} is not a recorded stat")
        keys.append(key)
    found = tuple(keys)
    allowed = (STAT_KEYS[position], ("bye",) + STAT_KEYS[position])
    if found not in allowed:
        raise ParseError(f"FantasyPros {position} columns do not match the consensus table")
    return found


def _normalize_positions(positions: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(positions, (tuple, list)) or not positions:
        raise ParseError("positions must list at least one of QB, RB, WR, TE, K, DST")
    names: list[str] = []
    for position in positions:
        if not isinstance(position, str):
            raise ParseError("positions must list at least one of QB, RB, WR, TE, K, DST")
        name = position.strip().upper()
        if name not in POSITIONS:
            raise ParseError("positions must list at least one of QB, RB, WR, TE, K, DST")
        names.append(name)
    return tuple(names)


def _week_query(week: int) -> str:
    if isinstance(week, bool) or not isinstance(week, int) or week < 1:
        raise ParseError("week must be an integer >= 1 or omitted for a season projection")
    return str(week)


class _ProjectionTableParser(HTMLParser):
    """Collect headers and player rows from a FantasyPros projection table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self.header_rows: list[list[dict[str, Any]]] = []
        self.saw_tbody = False
        self._in_thead = False
        self._in_header_row = False
        self._in_header_cell = False
        self._header_cells: list[dict[str, Any]] = []
        self._colspan = 1
        self._in_tbody = False
        self._in_row = False
        self._in_cell = False
        self._row_class = ""
        self._cells: list[dict[str, Any]] = []
        self._text: list[str] = []
        self._sort: str | None = None
        self._anchor: dict[str, Any] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "thead":
            self._in_thead = True
        elif self._in_thead and tag == "tr":
            self._in_header_row = True
            self._header_cells = []
        elif self._in_header_row and tag in {"td", "th"}:
            self._in_header_cell = True
            self._text = []
            raw_span = attributes.get("colspan") or "1"
            self._colspan = int(raw_span) if raw_span.isdigit() else 1
        elif tag == "tbody":
            self._in_tbody = True
            self.saw_tbody = True
        elif self._in_tbody and tag == "tr":
            self._in_row = True
            self._row_class = attributes.get("class", "")
            self._cells = []
        elif self._in_row and tag == "td":
            self._in_cell = True
            self._text = []
            sort = attributes.get("data-sort-value")
            self._sort = sort if sort else None
            self._anchor = {}
        elif self._in_cell and tag == "a":
            self._anchor = attributes

    def handle_endtag(self, tag: str) -> None:
        if tag == "thead":
            self._in_thead = False
        elif tag == "tr" and self._in_header_row:
            self._in_header_row = False
            self.header_rows.append(self._header_cells)
        elif tag in {"td", "th"} and self._in_header_cell:
            self._in_header_cell = False
            self._header_cells.append({"text": "".join(self._text), "colspan": self._colspan})
        elif tag == "tbody":
            self._in_tbody = False
        elif tag == "tr" and self._in_row:
            self._in_row = False
            classes = self._row_class.split()
            if any(part == "mpb-player" or part.startswith("mpb-player-") for part in classes):
                self.rows.append(self._cells)
        elif tag == "td" and self._in_cell:
            self._in_cell = False
            self._cells.append(
                {"text": "".join(self._text), "sort": self._sort, "anchor": dict(self._anchor)}
            )

    def handle_data(self, data: str) -> None:
        if self._in_header_cell or self._in_cell:
            self._text.append(data)
