"""CSV-Dateien einlesen und schreiben."""

from collections import defaultdict
import csv
import sys

from .constants import EXPECTED, KEY_COLS


def load(path):
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in EXPECTED if c not in (reader.fieldnames or [])]
            if missing:
                sys.exit(f"Fehler: In '{path}' fehlen Spalten: {', '.join(missing)}")
            rows = list(reader)
    except OSError as e:
        sys.exit(f"Fehler: '{path}' kann nicht gelesen werden: {e}")

    # Doppelte Schlüssel durchnummerieren, damit nichts verloren geht
    seen = defaultdict(int)
    entries = {}
    for row in rows:
        base = tuple(row[c] for c in KEY_COLS)
        seen[base] += 1
        entries[base + (seen[base],)] = row
    return entries


def write_csv(path, rows):
    """Schreibt Einträge im KeePassium-Spaltenformat (wieder importierbar)."""
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=EXPECTED, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    except OSError as e:
        sys.exit(f"Fehler: '{path}' kann nicht geschrieben werden: {e}")
