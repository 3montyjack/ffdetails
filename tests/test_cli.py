"""Command line records counts and writes the store."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

from ffdetails.__main__ import main
from ffdetails.errors import FetchError
from ffdetails.records import SleeperActual, freeze_stats
from ffdetails.recorder import Recorder
from ffdetails.store import RecordStore

STAMP = datetime(2026, 9, 23, tzinfo=timezone.utc)


class StubSleeper:
    def actuals(self, season, week, *, season_type="regular", recorded_at=None):
        return [
            SleeperActual(
                season=season,
                week=week,
                season_type=season_type,
                player_id="9",
                stats=freeze_stats({"pts_ppr": 1}),
                recorded_at=recorded_at or STAMP,
            )
        ]

    def projections(self, season, week, *, season_type="regular", recorded_at=None):
        raise FetchError("HTTP 503 for sleeper")


class CliTests(unittest.TestCase):
    def test_main_prints_the_recorded_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "kit.sqlite"
            store = RecordStore(db)
            recorder = Recorder(store, sleeper=StubSleeper())
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    ["--db", str(db), "sleeper-actuals", "--season", "2026", "--week", "1"],
                    recorder=recorder,
                )
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().strip(), "recorded 1 sleeper_actuals")
            self.assertEqual(store.sleeper_actuals(2026, 1)[0].player_id, "9")
            store.close()

    def test_main_reports_fetch_errors(self) -> None:
        store = RecordStore()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(
                ["sleeper-projections", "--season", "2026", "--week", "1"],
                recorder=Recorder(store, sleeper=StubSleeper()),
            )
        self.assertEqual(code, 1)
        self.assertIn("HTTP 503", stderr.getvalue())
        store.close()

    def test_help_lists_record_commands(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main([])
        self.assertEqual(code, 2)
        help_text = stdout.getvalue()
        self.assertIn("sleeper-actuals", help_text)
        self.assertIn("fantasypros-ranks", help_text)
        self.assertIn("fantasypros-accuracy", help_text)
        self.assertIn("waiver-bids", help_text)
        self.assertNotIn("lineup", help_text)


if __name__ == "__main__":
    unittest.main()
