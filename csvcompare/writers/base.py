"""Gemeinsame Grundlage der Writer und die Meldung, was ein Zielformat nicht speichern kann."""

from collections import Counter
from dataclasses import dataclass

from ..columns import ALL_NAMES, BY_NAME, LABELS, OLD_PASSWORDS_KEY, UNMAPPED_KEY

OLD_PASSWORDS_LABEL = "Frühere Passwörter"


@dataclass(frozen=True)
class Writer:
    """Ein Zielformat für Exporte.

    Ein konkreter Writer überschreibt ``text`` und nennt die Spalten, die er speichern kann.
    """

    format: str  # Kennung, siehe importers.base
    label: str  # Name für Anzeigen, z. B. „KeePass-CSV“
    extension: str  # Dateiendung samt Punkt
    mime: str  # Medientyp für Downloads
    columns: tuple  # Spalten, die das Zielformat speichern kann
    prefix_groups: bool = False  # setzt den Datenbanknamen wieder vor die Gruppenpfade
    stores_password_history: bool = False  # kann frühere Passwörter eines Eintrags speichern

    def text(self, rows):
        """Die Einträge als Dateiinhalt (String)."""
        raise NotImplementedError

    def write(self, path, rows):
        """Schreibt die Einträge in eine Datei. Wirft OSError, wenn das nicht gelingt."""
        with open(path, "w", newline="", encoding="utf-8") as f:
            f.write(self.text(rows))

    def keeps_source(self, row):
        """Kann das Format die nicht abgebildeten Originaldaten dieser Zeile wiederherstellen?"""
        return False

    def notes(self, rows):
        """Zusätzliche Hinweise zur Meldung nach einem Export (z. B. Unsicherheiten)."""
        return []


def has_data(column, row):
    """Steht in der Zeile in dieser Spalte etwas, das über den Standardwert hinausgeht?"""
    value = row.get(column, "")
    if column == "URLs":
        return len(value.split()) > 1  # die erste URL steht ohnehin in „URL“
    return value not in BY_NAME[column].defaults


def lost_data(rows, writer):
    """Zählt, bei wie vielen Einträgen das Zielformat Daten nicht speichern kann.

    Rückgabe: {"columns": {spalte: anzahl}, "source": {bezeichnung: anzahl}}.
    """
    columns, source = Counter(), Counter()
    for row in rows:
        for column in ALL_NAMES:
            if column not in writer.columns and has_data(column, row):
                columns[column] += 1
        if not writer.keeps_source(row):
            source.update(row.get(UNMAPPED_KEY) or [])
        if row.get(OLD_PASSWORDS_KEY) and not writer.stores_password_history:
            source[OLD_PASSWORDS_LABEL] += 1
    return {"columns": dict(columns), "source": dict(source)}


def loss_lines(lost, writer):
    """Zeilen für die Exportmeldung; leer, wenn nichts verloren geht."""
    parts = [f"{LABELS[column]} ({count})" for column, count in lost["columns"].items()]
    parts += [f"{label} ({count})" for label, count in lost["source"].items()]
    if not parts:
        return []
    return [
        f"  Im {writer.label} nicht speicherbar (Anzahl betroffener Einträge): " + ", ".join(parts)
    ]
