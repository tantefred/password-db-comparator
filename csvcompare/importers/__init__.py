"""Einlesen der unterstützten Exportformate in eine gemeinsame Darstellung."""

import csv
import io

from . import bitwarden, keepass_csv
from .base import CsvError, LoadResult

BOM = "\ufeff"


def load_any(name, text, keep_db_name=False):
    """Erkennt das Format am Inhalt und liest die Einträge. Wirft CsvError bei Problemen.

    name wird nur für Fehlermeldungen verwendet.
    """
    text = text.lstrip(BOM)
    if text.lstrip().startswith(("{", "[")):
        return bitwarden.parse_json(text, name)
    header = next(csv.reader(io.StringIO(text, newline="")), [])
    if bitwarden.is_csv(header):
        return bitwarden.parse_csv(text, name)
    return keepass_csv.parse(text, name, keep_db_name=keep_db_name)


__all__ = ["CsvError", "LoadResult", "load_any"]
