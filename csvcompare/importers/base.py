"""Gemeinsame Typen der Importer."""

from dataclasses import dataclass, field


class CsvError(Exception):
    """Eine Eingabedatei ist unbrauchbar (z. B. fehlende Spalten oder unbekanntes Format)."""


@dataclass
class LoadResult:
    """Ergebnis des Einlesens einer Datei, unabhängig vom Quellformat."""
    rows: list                 # ein Dict je Eintrag, Schlüssel sind Spaltennamen
    format: str                # Kennung des erkannten Formats, z. B. "keepass-csv"
    provided_columns: frozenset  # Spalten, die dieses Format tatsächlich liefert
    notes: list = field(default_factory=list)  # Hinweise für Nutzer (übersprungene Typen …)
