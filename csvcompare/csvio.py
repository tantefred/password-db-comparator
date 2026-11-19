"""CSV-Dateien einlesen und schreiben."""

from collections import defaultdict
import csv
import io
import sys

from .constants import EXPECTED, KEY_COLS
from .importers import CsvError, load_any


def entries_from_rows(rows):
    """Bildet aus Zeilen die Einträge, geordnet nach (Gruppe, Titel, Username, Nummer).

    Doppelte Schlüssel werden durchnummeriert, damit nichts verloren geht.
    """
    seen = defaultdict(int)
    entries = {}
    for row in rows:
        base = tuple(row[c] for c in KEY_COLS)
        seen[base] += 1
        entries[base + (seen[base],)] = row
    return entries


def read_file(path, keep_db_name=False):
    """Liest eine Datei als LoadResult; beendet das Programm mit einer Meldung bei Fehlern."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            text = f.read()
        return load_any(path, text, keep_db_name=keep_db_name)
    except CsvError as e:
        sys.exit(f"Fehler: {e}")
    except OSError as e:
        sys.exit(f"Fehler: '{path}' kann nicht gelesen werden: {e}")


def read_text(text, name, keep_db_name=False):
    """Liest Inhalt aus einem String (z. B. aus einem Upload). Wirft CsvError."""
    return load_any(name, text, keep_db_name=keep_db_name)


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
