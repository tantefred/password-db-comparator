"""Zielformate für Exporte und die Meldung, was ein Zielformat nicht speichern kann.

Aktuell gibt es nur das KeePass-CSV. Ein weiteres Format (z. B. Bitwarden-JSON) bekommt
einen eigenen Writer mit denselben Methoden ``text`` und ``write`` sowie der Liste der Spalten,
die er speichern kann; ``lost_data`` meldet dann automatisch, was beim Schreiben verloren ginge.
"""

import csv
import io
from collections import Counter
from dataclasses import dataclass

from .columns import ALL_NAMES, BY_NAME, CORE_NAMES, LABELS, UNMAPPED_KEY
from .importers import KEEPASS_CSV


@dataclass(frozen=True)
class CsvWriter:
    format: str
    label: str
    columns: tuple                 # Spalten, die das Zielformat speichern kann
    restores_source: bool = False  # kann nicht abgebildete Originaldaten (_source) wiederherstellen

    def _write(self, fileobj, rows):
        writer = csv.DictWriter(fileobj, fieldnames=self.columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    def text(self, rows):
        """Die Einträge als Dateiinhalt (String)."""
        buffer = io.StringIO(newline="")
        self._write(buffer, rows)
        return buffer.getvalue()

    def write(self, path, rows):
        """Schreibt die Einträge in eine Datei. Wirft OSError, wenn das nicht gelingt."""
        with open(path, "w", newline="", encoding="utf-8") as f:
            self._write(f, rows)


KEEPASS_CSV_WRITER = CsvWriter(KEEPASS_CSV, "KeePass-CSV", CORE_NAMES)
DEFAULT_WRITER = KEEPASS_CSV_WRITER


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
        for column in ALL_NAMES:
            if column not in writer.columns and has_data(column, row):
                columns[column] += 1
        if not writer.restores_source:
            source.update(row.get(UNMAPPED_KEY) or [])
    return {"columns": dict(columns), "source": dict(source)}


def loss_lines(lost, writer=DEFAULT_WRITER):
    """Zeilen für die Exportmeldung; leer, wenn nichts verloren geht."""
    parts = [f"{LABELS[column]} ({count})" for column, count in lost["columns"].items()]
    parts += [f"{label} ({count})" for label, count in lost["source"].items()]
    if not parts:
        return []
    return [f"  Im {writer.label} nicht speicherbar (Anzahl betroffener Einträge): "
            + ", ".join(parts)]
