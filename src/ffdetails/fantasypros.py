"""Read FantasyPros consensus projections and weekly ranking boards."""

from __future__ import annotations

import json
import re
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, Sequence
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from ffdetails.errors import ParseError
from ffdetails.http import UrllibClient
from ffdetails.records import (
    FantasyProsExpert,
    FantasyProsProjection,
    FantasyProsRank,
    freeze_stats,
)
from ffdetails.timeutil import as_utc

FANTASYPROS_PROJECTIONS = "https://www.fantasypros.com/nfl/projections"
FANTASYPROS_RANKINGS = "https://www.fantasypros.com/nfl/rankings"
FANTASYPROS_ORIGIN = "https://www.fantasypros.com"
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
    """Fetch published FantasyPros consensus projections and ranking boards."""

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

    def positional_ranks(
        self,
        season: int,
        week: int,
        *,
        positions: tuple[str, ...] | list[str] = POSITIONS,
        scoring: str = "HALF",
        recorded_at: datetime | None = None,
    ) -> tuple[list[FantasyProsExpert], list[FantasyProsRank]]:
        """Fetch expert directories and the chosen public board at each position.

        RB, WR, and TE use the requested scoring. QB, K, and DST stay on the
        standard board FantasyPros publishes for those positions.
        """
        stamp = as_utc(recorded_at)
        scoring_name = normalize_scoring(scoring)
        chosen_positions = _normalize_positions(positions)
        experts: list[FantasyProsExpert] = []
        for position in chosen_positions:
            board_scoring = published_scoring(position, scoring_name)
            html = self.http.get_text(rankings_url(position, week, scoring_name))
            experts.extend(
                parse_rank_experts(
                    html,
                    season=season,
                    week=week,
                    position=position,
                    scoring=board_scoring,
                    recorded_at=stamp,
                )
            )
        chosen = choose_positional_experts(experts, positions=chosen_positions)
        ranks: list[FantasyProsRank] = []
        for expert in chosen:
            if not expert.rankings_url:
                raise ParseError(f"FantasyPros {expert.position} ranker has no public board")
            html = self.http.get_text(expert.rankings_url)
            ranks.extend(parse_expert_ranks(html, expert=expert))
        return experts, ranks


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


# QB, K, and DST pages are published once. Reception scoring changes RB, WR, and TE only.
_STANDARD_RANK_POSITIONS = frozenset({"QB", "K", "DST"})
_OPTION_TAG = re.compile(r"<option\b([^>]*)>", re.IGNORECASE)
_SELECTED_ATTR = re.compile(r"\bselected\b", re.IGNORECASE)
_OPTION_VALUE = re.compile(r"""\bvalue=["']([^"']*)["']""", re.IGNORECASE)


def published_scoring(position: str, scoring: str) -> str:
    """Scoring view FantasyPros publishes for a position."""
    position_name = _normalize_positions((position,))[0]
    scoring_name = normalize_scoring(scoring)
    if position_name in _STANDARD_RANK_POSITIONS:
        return "STD"
    return scoring_name


def rankings_url(position: str, week: int, scoring: str = "HALF") -> str:
    position_name = _normalize_positions((position,))[0]
    board_scoring = published_scoring(position_name, scoring)
    week_query = _week_query(week)
    slug = position_name.lower()
    if board_scoring == "HALF":
        slug = f"half-point-ppr-{slug}"
    elif board_scoring == "PPR":
        slug = f"ppr-{slug}"
    return f"{FANTASYPROS_RANKINGS}/{slug}.php?week={week_query}"


def parse_rank_experts(
    html: str,
    *,
    season: int,
    week: int,
    position: str,
    scoring: str,
    recorded_at: datetime,
) -> list[FantasyProsExpert]:
    _require_season(season)
    week_query = _week_query(week)
    position_name = _normalize_positions((position,))[0]
    scoring_name = normalize_scoring(scoring)
    payload = _assigned_object(html, "var ecrData = ")
    _require_rank_page(
        payload,
        season=season,
        week=week_query,
        position=position_name,
        scoring=scoring_name,
    )
    groups = _assigned_object(html, "var expertGroupsData = ")
    raw_experts = groups.get("expert_data")
    if not isinstance(raw_experts, list) or not raw_experts:
        raise ParseError(f"FantasyPros {position_name} page has no expert directory")
    stamp = as_utc(recorded_at)
    records: list[FantasyProsExpert] = []
    for raw in raw_experts:
        record = _expert_record(
            raw,
            season=season,
            week=int(week_query),
            position=position_name,
            scoring=scoring_name,
            recorded_at=stamp,
        )
        if record is not None:
            records.append(record)
    if not records:
        raise ParseError(f"FantasyPros {position_name} page has no expert directory")
    return records


def parse_expert_ranks(html: str, *, expert: FantasyProsExpert) -> list[FantasyProsRank]:
    if expert.accuracy_rank is None:
        raise ParseError(f"FantasyPros {expert.position} board for {expert.name} has no accuracy rank")
    _require_selected_board(
        html,
        week=expert.week,
        position=expert.position,
        scoring=expert.scoring,
    )
    parser = _ExpertBoardParser()
    parser.feed(html)
    parser.close()
    if not parser.rows:
        raise ParseError(f"FantasyPros {expert.position} board for {expert.name} has no players")
    records: list[FantasyProsRank] = []
    for cells in parser.rows:
        record = _board_row(cells, expert=expert)
        if record is not None:
            records.append(record)
    if not records:
        raise ParseError(f"FantasyPros {expert.position} board for {expert.name} has no players")
    return records


def choose_positional_experts(
    experts: Sequence[FantasyProsExpert],
    *,
    positions: Sequence[str] | None = None,
) -> tuple[FantasyProsExpert, ...]:
    """Pick one public board per position.

    The expert with the best in-season positional accuracy rank wins. Experts
    without a public board are left out. Equal ranks keep the lower expert id.
    """
    if positions is None:
        requested = tuple(dict.fromkeys(expert.position for expert in experts))
    else:
        requested = _normalize_positions(tuple(positions))
    chosen: dict[str, FantasyProsExpert] = {}
    for expert in experts:
        if expert.accuracy_rank is None or not expert.rankings_url:
            continue
        if expert.position not in requested:
            continue
        current = chosen.get(expert.position)
        if current is None or _expert_key(expert) < _expert_key(current):
            chosen[expert.position] = expert
    missing = [position for position in requested if position not in chosen]
    if missing:
        names = ", ".join(missing)
        raise ParseError(f"FantasyPros has no public in-season ranker for {names}")
    return tuple(chosen[position] for position in requested)


def hybrid_board(
    experts: Sequence[FantasyProsExpert],
    ranks: Sequence[FantasyProsRank],
    *,
    scoring: str = "HALF",
) -> list[FantasyProsRank]:
    """Return the chosen public board at each position.

    ``scoring`` selects the RB, WR, and TE view. QB, K, and DST stay on STD.
    """
    scoring_name = normalize_scoring(scoring)
    filtered = [
        expert
        for expert in experts
        if expert.scoring == published_scoring(expert.position, scoring_name)
    ]
    chosen = choose_positional_experts(filtered)
    keys = {(expert.position, expert.scoring, expert.expert_id) for expert in chosen}
    selected = [
        rank
        for rank in ranks
        if (rank.position, rank.scoring, rank.expert_id) in keys
    ]
    order = {position: index for index, position in enumerate(POSITIONS)}
    selected.sort(key=lambda rank: (order.get(rank.position, len(order)), rank.rank, rank.player_id))
    return selected


def _expert_key(expert: FantasyProsExpert) -> tuple[int, int, str]:
    expert_id = expert.expert_id
    numeric = int(expert_id) if expert_id.isdigit() else 10**12
    return (expert.accuracy_rank or 10**9, numeric, expert_id)


def _require_season(season: int) -> None:
    if not isinstance(season, int) or isinstance(season, bool) or season < 2000:
        raise ParseError("season must be an integer year")


def _assigned_object(html: str, marker: str) -> dict[str, Any]:
    index = html.find(marker)
    if index < 0:
        raise ParseError(f"FantasyPros page is missing {marker.strip()}")
    start = html.find("{", index)
    if start < 0 or start - index > len(marker) + 5:
        raise ParseError(f"FantasyPros page is missing {marker.strip()}")
    try:
        payload, _end = json.JSONDecoder().raw_decode(html[start:])
    except json.JSONDecodeError as exc:
        raise ParseError(f"FantasyPros page has invalid {marker.strip()}") from exc
    if not isinstance(payload, dict):
        raise ParseError(f"FantasyPros page has invalid {marker.strip()}")
    return payload


def _require_rank_page(
    payload: dict[str, Any],
    *,
    season: int,
    week: str,
    position: str,
    scoring: str,
) -> None:
    if str(payload.get("year")) != str(season):
        raise ParseError(f"FantasyPros {position} rankings are not for {season}")
    if str(payload.get("week")) != week:
        raise ParseError(f"FantasyPros {position} rankings are not for week {week}")
    if str(payload.get("position_id")) != position:
        raise ParseError(f"FantasyPros rankings page is not {position}")
    if str(payload.get("scoring")) != scoring:
        raise ParseError(f"FantasyPros {position} rankings are not {scoring}")
    if str(payload.get("type", "")).lower().startswith("draft"):
        raise ParseError(f"FantasyPros {position} rankings are a draft board")


def _expert_record(
    raw: Any,
    *,
    season: int,
    week: int,
    position: str,
    scoring: str,
    recorded_at: datetime,
) -> FantasyProsExpert | None:
    if not isinstance(raw, dict):
        return None
    expert_id = raw.get("id")
    name = raw.get("name")
    if isinstance(expert_id, bool) or not isinstance(expert_id, (int, str)):
        return None
    expert_key = str(expert_id).strip()
    if not expert_key or not isinstance(name, str) or not name.strip():
        return None
    site = raw.get("site")
    site_name = site.strip() if isinstance(site, str) and site.strip() else None
    link = raw.get("rankings_link")
    url = None
    if isinstance(link, str) and link.strip():
        url = _with_week(urljoin(FANTASYPROS_ORIGIN, link.strip()), week)
    return FantasyProsExpert(
        season=season,
        week=week,
        position=position,
        scoring=scoring,
        expert_id=expert_key,
        name=name.strip(),
        site=site_name,
        accuracy_rank=_accuracy_rank(raw.get("in_season_pos_rank")),
        rankings_url=url,
        recorded_at=recorded_at,
    )


def _accuracy_rank(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    if isinstance(raw, str) and raw.strip().isdigit():
        value = int(raw.strip())
        return value if value >= 1 else None
    return None


def _with_week(url: str, week: int) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["week"] = str(week)
    return urlunsplit(parts._replace(query=urlencode(query)))


def _require_selected_board(html: str, *, week: int, position: str, scoring: str) -> None:
    for value in _selected_option_values(html):
        query = dict(parse_qsl(urlsplit(urljoin(FANTASYPROS_ORIGIN, value)).query))
        if (
            query.get("week") == str(week)
            and query.get("position") == position
            and query.get("scoring") == scoring
        ):
            return
    raise ParseError(
        f"FantasyPros {position} board is not week {week} {scoring}"
    )


def _selected_option_values(html: str) -> list[str]:
    values: list[str] = []
    for match in _OPTION_TAG.finditer(html):
        attrs = match.group(1)
        if _SELECTED_ATTR.search(attrs) is None:
            continue
        value = _OPTION_VALUE.search(attrs)
        if value is not None:
            values.append(unescape(value.group(1)))
    return values


def _board_row(cells: list[dict[str, Any]], *, expert: FantasyProsExpert) -> FantasyProsRank | None:
    if len(cells) < 4:
        return None
    player_id, name = _player_identity(cells[1])
    if player_id is None:
        return None
    if not name:
        raise ParseError(f"FantasyPros {expert.position} board row is missing a player name")
    rank = _plain_int(cells[0].get("text"), label=f"{name} rank")
    if rank is None or rank < 1:
        raise ParseError(f"FantasyPros {expert.position} rank for {name} is missing")
    # Skill and kicker boards are rank, player, team, opponent, ECR.
    # Team defenses omit the team abbreviation, so opponent and ECR shift left.
    if len(cells) >= 6:
        team = _blank_text(cells[2].get("text"))
        opponent = _blank_text(cells[3].get("text"))
        ecr = _plain_int(cells[4].get("text"), label=None)
    else:
        team = None
        opponent = _blank_text(cells[2].get("text"))
        ecr = _plain_int(cells[3].get("text"), label=None)
    return FantasyProsRank(
        season=expert.season,
        week=expert.week,
        position=expert.position,
        scoring=expert.scoring,
        expert_id=expert.expert_id,
        expert_name=expert.name,
        accuracy_rank=expert.accuracy_rank,
        player_id=player_id,
        name=name,
        team=team,
        opponent=opponent,
        rank=rank,
        ecr=ecr,
        recorded_at=expert.recorded_at,
    )


def _player_identity(cell: dict[str, Any]) -> tuple[str | None, str]:
    anchor = cell.get("anchor") or {}
    match = _PLAYER_ID.search(str(anchor.get("class") or ""))
    raw_name = anchor.get("fp-player-name") or _collapsed(str(cell.get("text") or ""))
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if match is not None:
        return match.group(1), name
    href = str(anchor.get("href") or "")
    leaf = urlsplit(href).path.rstrip("/").split("/")[-1]
    if leaf.endswith(".php"):
        leaf = leaf[: -len(".php")]
    slug = leaf.strip()
    if not slug or not name:
        return None, name
    return slug, name


def _blank_text(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    text = _collapsed(raw)
    return text or None


def _plain_int(raw: Any, *, label: str | None) -> int | None:
    if not isinstance(raw, str):
        if label is None:
            return None
        raise ParseError(f"FantasyPros {label} is missing")
    token = _collapsed(raw).replace(",", "")
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if label is None:
        return None
    raise ParseError(f"FantasyPros {label} is not a number: {token!r}")


class _ExpertBoardParser(HTMLParser):
    """Collect player rows from a published expert ranking table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._table_depth = 0
        self._target_depth = 0
        self._in_target = False
        self._in_row = False
        self._in_cell = False
        self._cells: list[dict[str, Any]] = []
        self._text: list[str] = []
        self._anchor: dict[str, Any] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if tag == "table":
            self._table_depth += 1
            if attributes.get("id") == "data":
                self._in_target = True
                self._target_depth = self._table_depth
        elif self._in_target and tag == "tr" and not self._in_row:
            self._in_row = True
            self._cells = []
        elif self._in_row and tag == "td" and not self._in_cell:
            self._in_cell = True
            self._text = []
            self._anchor = {}
        elif self._in_cell and tag == "a" and not self._anchor:
            self._anchor = attributes

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._table_depth:
            if self._in_target and self._table_depth == self._target_depth:
                self._in_target = False
            self._table_depth -= 1
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._cells:
                self.rows.append(self._cells)
        elif tag == "td" and self._in_cell:
            self._in_cell = False
            self._cells.append({"text": "".join(self._text), "anchor": dict(self._anchor)})

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._text.append(data)
