"""The package records details and does not grow lineup or bid decisions."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "ffdetails"
FORBIDDEN = (
    "recommend",
    "advice",
    "lineup",
    "optimize",
    "suggest",
    "start_sit",
    "sit_start",
    "waiver_advice",
    "bid_suggestion",
)


class BoundaryTests(unittest.TestCase):
    def test_public_names_stay_on_recording(self) -> None:
        import ffdetails

        names = [name.lower() for name in ffdetails.__all__]
        for forbidden in FORBIDDEN:
            for name in names:
                self.assertNotIn(forbidden, name)

    def test_source_definitions_stay_on_recording(self) -> None:
        found: list[str] = []
        for path in ROOT.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    found.append(node.name.lower())
        for forbidden in FORBIDDEN:
            for name in found:
                self.assertNotIn(forbidden, name, f"{forbidden} appears in {name}")


if __name__ == "__main__":
    unittest.main()
