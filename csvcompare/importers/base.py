"""Gemeinsame Typen der Importer."""

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
