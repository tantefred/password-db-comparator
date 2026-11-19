"""Zielformate für Exporte und die Meldung, was ein Zielformat nicht speichern kann.

Aktuell gibt es nur das KeePass-CSV. Weitere Formate (Bitwarden-CSV/-JSON) lassen sich hier
ergänzen: Ein ``Writer`` nennt die Spalten, die er speichern kann, und ``lost_data`` meldet
für beliebige Zeilen, was beim Schreiben verloren ginge.
"""

import csv
import io
import sys
from collections import Counter
from dataclasses import dataclass

from .columns import ALL_NAMES, BY_NAME, CORE_NAMES, LABELS, UNMAPPED_KEY


@dataclass(frozen=True)
class Writer:
    format: str
    label: str
    columns: tuple           # Spalten, die das Zielformat speichern kann
    restores_source: bool = False  # kann nicht abgebildete Originaldaten (_source) wiederherstellen

    def text(self, rows):
        """Die Einträge als Dateiinhalt (String)."""
        raise NotImplementedError

    def write(self, path, rows):
        """Schreibt die Einträge in eine Datei."""
        raise NotImplementedError


def write_csv_rows(fileobj, rows):
    writer = csv.DictWriter(fileobj, fieldnames=CORE_NAMES, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)


class KeePassCsvWriter(Writer):
    def text(self, rows):
        buffer = io.StringIO(newline="")
        write_csv_rows(buffer, rows)
        return buffer.getvalue()

    def write(self, path, rows):
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                write_csv_rows(f, rows)
        except OSError as e:
            sys.exit(f"Fehler: '{path}' kann nicht geschrieben werden: {e}")


KEEPASS_CSV = KeePassCsvWriter("keepass-csv", "KeePass-CSV", CORE_NAMES)
WRITERS = {KEEPASS_CSV.format: KEEPASS_CSV}
DEFAULT_WRITER = KEEPASS_CSV


def has_data(column, row):
    """Steht in der Zeile in dieser Spalte etwas, das über den Standardwert hinausgeht?"""
    value = row.get(column, "")
    if column == "URLs":
        return len(value.split()) > 1  # die erste URL steht ohnehin in „URL“
    return value not in BY_NAME[column].defaults


def lost_data(rows, writer=DEFAULT_WRITER):
    """Zählt, bei wie vielen Einträgen das Zielformat Daten nicht speichern kann.

    Rückgabe: {"columns": {spalte: anzahl}, "source": {bezeichnung: anzahl}}.
    """
    columns, source = Counter(), Counter()
    for row in rows:
        for col in ALL_NAMES:
            if col not in writer.columns and has_data(col, row):
                columns[col] += 1
        if not writer.restores_source:
            for label in row.get(UNMAPPED_KEY) or []:
                source[label] += 1
    return {"columns": dict(columns), "source": dict(source)}


def loss_lines(lost, writer=DEFAULT_WRITER):
    """Zeilen für die Exportmeldung; leer, wenn nichts verloren geht."""
    parts = [f"{LABELS[col]} ({n})" for col, n in lost["columns"].items()]
    parts += [f"{label} ({n})" for label, n in lost["source"].items()]
    if not parts:
        return []
    return [f"  Im {writer.label} nicht speicherbar (Anzahl betroffener Einträge): "
            + ", ".join(parts)]
