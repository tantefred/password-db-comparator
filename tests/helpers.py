"""Gemeinsame Hilfen der Tests: Importpfad, Beispieldateien lesen, das Skript aufrufen."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "compare_csv.py")
sys.path.insert(0, ROOT)  # damit die Tests das Paket csvcompare finden


def fixture_path(name):
    """Absoluter Pfad einer Beispieldatei in tests/."""
    return os.path.join(ROOT, "tests", name)


def read_fixture(name):
    """Inhalt einer Beispieldatei in tests/ (Zeilenenden unverändert)."""
    with open(fixture_path(name), encoding="utf-8", newline="") as f:
        return f.read()


def run(*args):
    """Startet das Skript im Projektverzeichnis und gibt (returncode, stdout, stderr) zurück."""
    proc = subprocess.run(
        [sys.executable, SCRIPT, *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_json(*args):
    """Startet das Skript mit ``--format json`` und gibt (returncode, objekt) zurück."""
    rc, out, _ = run(*args, "--format", "json")
    return rc, json.loads(out)


def titles(entries):
    """Sortierte Titel aus einer Liste von JSON-Einträgen."""
    return sorted(entry["title"] for entry in entries)
