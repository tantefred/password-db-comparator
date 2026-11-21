"""Stilprüfung: Linter und Formatter (ruff) müssen mit dem Code zufrieden sein.

Läuft nur, wenn ruff installiert ist (``pip install -r requirements-dev.txt``).
"""

import importlib.util
import subprocess
import sys
import unittest

from tests.helpers import ROOT


def run_ruff(*args):
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", *args], cwd=ROOT, capture_output=True, text=True
    )
    return proc.returncode, proc.stdout + proc.stderr


@unittest.skipUnless(
    importlib.util.find_spec("ruff"), "ruff ist nicht installiert (requirements-dev.txt)"
)
class StyleTests(unittest.TestCase):
    def test_linter_finds_nothing(self):
        rc, output = run_ruff("check", ".")
        self.assertEqual(rc, 0, f"ruff check meldet Probleme:\n{output}")

    def test_code_is_formatted(self):
        rc, output = run_ruff("format", "--check", ".")
        self.assertEqual(
            rc, 0, f"ruff format würde etwas ändern (ruff format . ausführen):\n{output}"
        )


if __name__ == "__main__":
    unittest.main()
