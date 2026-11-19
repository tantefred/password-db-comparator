"""Einlesen der unterstützten Exportformate in eine gemeinsame Darstellung."""

import csv
import io

from . import bitwarden, keepass_csv
from .base import BITWARDEN_CSV, BITWARDEN_JSON, FORMAT_LABELS, KEEPASS_CSV, CsvError, LoadResult

BOM = "\ufeff"


def load_any(name, text, keep_db_name=False):
    """Erkennt das Format am Inhalt und liest die Einträge. Wirft CsvError bei Problemen.

    ``name`` wird nur für Fehlermeldungen verwendet.
    """
    text = text.lstrip(BOM)
    if text.lstrip().startswith(("{", "[")):
        return bitwarden.parse_json(text, name)
    header = next(csv.reader(io.StringIO(text, newline="")), [])
    if bitwarden.is_csv(header):
        return bitwarden.parse_csv(text, name)
    return keepass_csv.parse(text, name, keep_db_name=keep_db_name)


def read_file(path, keep_db_name=False):
    """Liest eine Datei und erkennt das Format. Wirft CsvError, wenn das nicht gelingt."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            text = f.read()
    except OSError as e:
        raise CsvError(f"'{path}' kann nicht gelesen werden: {e}") from None
    except UnicodeDecodeError:
        raise CsvError(f"'{path}' ist keine UTF-8-Textdatei und kann nicht gelesen werden.") from None
    return load_any(path, text, keep_db_name=keep_db_name)


__all__ = ["BITWARDEN_CSV", "BITWARDEN_JSON", "FORMAT_LABELS", "KEEPASS_CSV", "CsvError",
           "LoadResult", "load_any", "read_file"]
