"""CSV-Dateien einlesen und schreiben."""

from collections import defaultdict
import csv
import io
import sys

from .constants import EXPECTED, KEY_COLS


class CsvError(Exception):
    """Eine CSV-Datei ist unbrauchbar (z. B. fehlende Spalten)."""


def read_entries(fileobj, name):
    """Liest Einträge aus einem geöffneten CSV-Objekt.

    Doppelte Schlüssel werden durchnummeriert, damit nichts verloren geht.
    Wirft CsvError, wenn Pflichtspalten fehlen.
    """
    reader = csv.DictReader(fileobj)
    missing = [c for c in EXPECTED if c not in (reader.fieldnames or [])]
    if missing:
        raise CsvError(f"In '{name}' fehlen Spalten: {', '.join(missing)}")
    seen = defaultdict(int)
    entries = {}
    for row in reader:
        base = tuple(row[c] for c in KEY_COLS)
        seen[base] += 1
        entries[base + (seen[base],)] = row
    return entries


def load(path):
    """Liest eine CSV-Datei; beendet das Programm mit einer Meldung bei Fehlern."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return read_entries(f, path)
    except CsvError as e:
        sys.exit(f"Fehler: {e}")
    except OSError as e:
        sys.exit(f"Fehler: '{path}' kann nicht gelesen werden: {e}")


def load_text(text, name):
    """Liest CSV-Inhalt aus einem String (z. B. aus einem Upload). Wirft CsvError."""
    return read_entries(io.StringIO(text.lstrip("\ufeff"), newline=""), name)


def write_rows(fileobj, rows):
    w = csv.DictWriter(fileobj, fieldnames=EXPECTED, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)


def csv_text(rows):
    """Einträge im KeePassium-Spaltenformat als String (wieder importierbar)."""
    buf = io.StringIO(newline="")
    write_rows(buf, rows)
    return buf.getvalue()


def write_csv(path, rows):
    """Schreibt Einträge im KeePassium-Spaltenformat (wieder importierbar)."""
    try:
        with open(path, "w", newline="", encoding="utf-8") as f:
            write_rows(f, rows)
    except OSError as e:
        sys.exit(f"Fehler: '{path}' kann nicht geschrieben werden: {e}")
