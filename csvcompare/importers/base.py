"""Gemeinsame Typen der Importer."""

import csv
import io
from dataclasses import dataclass, field

from ..columns import FORMAT_KEY

# Kennungen der unterstützten Formate und ihre Namen für Anzeigen
KEEPASS_CSV = "keepass-csv"
BITWARDEN_JSON = "bitwarden-json"
BITWARDEN_CSV = "bitwarden-csv"
FORMAT_LABELS = {
    KEEPASS_CSV: "KeePass-CSV",
    BITWARDEN_JSON: "Bitwarden-JSON",
    BITWARDEN_CSV: "Bitwarden-CSV",
}


class CsvError(Exception):
    """Eine Eingabedatei ist unbrauchbar (z. B. fehlende Spalten oder unbekanntes Format)."""


class CsvTable:
    """Eine gelesene CSV-Datei: Kopfzeile, Zeilen als Dicts und was dabei auffiel."""

    def __init__(self, text):
        reader = csv.reader(io.StringIO(text, newline=""))
        self.fieldnames = next(reader, None) or []
        self.rows = []
        self.short_rows = 0  # Zeilen mit weniger Zellen als die Kopfzeile
        self.first_short_line = None
        for cells in reader:
            if not cells:  # leere Zeilen überspringen
                continue
            if len(cells) < len(self.fieldnames):
                self.short_rows += 1
                self.first_short_line = self.first_short_line or reader.line_num
                cells = cells + [""] * (len(self.fieldnames) - len(cells))
            self.rows.append(dict(zip(self.fieldnames, cells, strict=False)))

    def notes(self):
        """Hinweis auf zu kurze Zeilen (deren fehlende Felder bleiben leer)."""
        if not self.short_rows:
            return []
        return [
            f"{self.short_rows} Zeilen haben weniger Spalten als die Kopfzeile "
            f"(erste: Zeile {self.first_short_line}); fehlende Felder bleiben leer."
        ]


@dataclass
class LoadResult:
    """Ergebnis des Einlesens einer Datei, unabhängig vom Quellformat."""

    rows: list  # ein Dict je Eintrag, Schlüssel sind Spaltennamen
    format: str  # Kennung des erkannten Formats (siehe oben)
    provided_columns: frozenset  # Spalten, die dieses Format tatsächlich liefert
    notes: list = field(default_factory=list)  # Hinweise für Nutzer (übersprungene Typen …)
    db_prefix: str = None  # Datenbankname, der aus den Gruppenpfaden entfernt wurde

    def __post_init__(self):
        for row in self.rows:  # jede Zeile weiß, aus welchem Format sie stammt
            row[FORMAT_KEY] = self.format
