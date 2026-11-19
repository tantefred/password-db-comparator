"""Einlesen der unterstützten Exportformate in eine gemeinsame Darstellung."""

from . import keepass_csv
from .base import CsvError, LoadResult


def load_any(name, text, keep_db_name=False):
    """Erkennt das Format am Inhalt und liest die Einträge. Wirft CsvError bei Problemen.

    name wird nur für Fehlermeldungen verwendet.
    """
    text = text.lstrip("﻿")
    return keepass_csv.parse(text, name, keep_db_name=keep_db_name)


__all__ = ["CsvError", "LoadResult", "load_any"]
