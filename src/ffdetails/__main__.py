"""Command line for recording details into a sqlite file."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from ffdetails.errors import FfdetailsError
from ffdetails.fantasypros import FantasyProsSource
from ffdetails.http import UrllibClient
from ffdetails.recorder import Recorder
from ffdetails.sleeper import SleeperSource
from ffdetails.store import RecordStore


def main(argv: Sequence[str] | None = None, *, recorder: Recorder | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        if args.command == "stat-model":
            from ffdetails.statmodel import write_stat_model

            count = write_stat_model(UrllibClient(), args.out)
            print(f"wrote {args.out} ({count} holdout games)")
            return 0
        count = run(args, recorder=recorder)
    except FfdetailsError as exc:
        print(f"ffdetails: {exc}", file=sys.stderr)
        return 1
    print(f"recorded {count} {args.command.replace('-', '_')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ffdetails",
        description="Record Sleeper and FantasyPros details.",
    )
    parser.add_argument("--db", default="ffdetails.sqlite", help="sqlite file to append to")
    sub = parser.add_subparsers(dest="command")

    actuals = sub.add_parser("sleeper-actuals", help="record Sleeper weekly actuals")
    _add_sleeper_week(actuals)

    projections = sub.add_parser("sleeper-projections", help="record Sleeper weekly projections")
    _add_sleeper_week(projections)

    consensus = sub.add_parser(
        "fantasypros-projections",
        help="record FantasyPros consensus projections",
    )
    consensus.add_argument("--season", type=int, required=True)
    week = consensus.add_mutually_exclusive_group(required=True)
    week.add_argument("--week", type=int)
    week.add_argument("--season-long", action="store_true")
    consensus.add_argument("--scoring", default="HALF", choices=["STD", "HALF", "PPR"])
    consensus.add_argument(
        "--positions",
        default="QB,RB,WR,TE,K,DST",
        help="comma-separated positions",
    )

    ranks = sub.add_parser(
        "fantasypros-ranks",
        help="record the public weekly board of the best in-season ranker at each position",
    )
    ranks.add_argument("--season", type=int, required=True)
    ranks.add_argument("--week", type=int, required=True)
    ranks.add_argument("--scoring", default="HALF", choices=["STD", "HALF", "PPR"])
    ranks.add_argument(
        "--positions",
        default="QB,RB,WR,TE,K,DST",
        help="comma-separated positions",
    )
    ranks.add_argument(
        "--per-position",
        type=int,
        default=1,
        help="public boards to keep at each position after accuracy-window leaders",
    )
    ranks.add_argument(
        "--through-week",
        type=int,
        help="also record accuracy for the season and each week through this one",
    )

    accuracy = sub.add_parser(
        "fantasypros-accuracy",
        help="record FantasyPros accuracy for the season or one week",
    )
    accuracy.add_argument("--season", type=int, required=True)
    window = accuracy.add_mutually_exclusive_group()
    window.add_argument("--week", type=int, help="one completed week; omit for season to date")
    window.add_argument(
        "--through-week",
        type=int,
        help="season to date plus each week through this one",
    )

    sub.add_parser("injury-tags", help="record Sleeper injury tags")

    bids = sub.add_parser("waiver-bids", help="record Sleeper waiver claim bids")
    bids.add_argument("--league-id", required=True)
    bids.add_argument("--season", type=int, required=True)
    bids.add_argument("--week", type=int, required=True)

    stat_model = sub.add_parser(
        "stat-model",
        help="fit moneylines and injury reports into the agent stat note",
    )
    stat_model.add_argument(
        "--out",
        default="AGENT_STAT.md",
        help="markdown file to write",
    )
    return parser


def run(args: argparse.Namespace, *, recorder: Recorder | None = None) -> int:
    owns_store = recorder is None
    store = RecordStore(args.db) if recorder is None else recorder.store
    if recorder is None:
        client = UrllibClient()
        recorder = Recorder(
            store,
            sleeper=SleeperSource(client),
            fantasypros=FantasyProsSource(client),
        )
    try:
        if args.command == "sleeper-actuals":
            records = recorder.record_sleeper_actuals(
                args.season, args.week, season_type=args.season_type
            )
        elif args.command == "sleeper-projections":
            records = recorder.record_sleeper_projections(
                args.season, args.week, season_type=args.season_type
            )
        elif args.command == "fantasypros-projections":
            week = None if args.season_long else args.week
            positions = tuple(part.strip() for part in args.positions.split(",") if part.strip())
            records = recorder.record_fantasypros_projections(
                args.season, week, positions=positions, scoring=args.scoring
            )
        elif args.command == "fantasypros-ranks":
            positions = tuple(part.strip() for part in args.positions.split(",") if part.strip())
            records = recorder.record_fantasypros_ranks(
                args.season,
                args.week,
                positions=positions,
                scoring=args.scoring,
                per_position=args.per_position,
                through_week=args.through_week,
            )
        elif args.command == "fantasypros-accuracy":
            records = recorder.record_fantasypros_accuracy(
                args.season,
                args.week,
                through_week=args.through_week,
            )
        elif args.command == "injury-tags":
            records = recorder.record_injury_tags()
        elif args.command == "waiver-bids":
            records = recorder.record_waiver_bids(args.league_id, args.season, args.week)
        else:
            raise FfdetailsError(f"unknown command {args.command}")
        return len(records)
    finally:
        if owns_store:
            store.close()


def _add_sleeper_week(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument(
        "--season-type",
        default="regular",
        choices=["regular", "post", "pre"],
    )


if __name__ == "__main__":
    raise SystemExit(main())
