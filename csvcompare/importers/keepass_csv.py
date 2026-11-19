"""KeePassium/KeePassXC-CSV: Group, Title, Username, Password, URL, Notes, TOTP, Icon,
Last Modified, Created."""

import csv
import io

from ..columns import CORE_NAMES
from .base import KEEPASS_CSV, CsvError, LoadResult


def strip_db_prefix(rows):
    """Entfernt den Datenbanknamen, mit dem KeePassium jeden Gruppenpfad beginnt.

    Nur wenn **alle** Einträge dasselbe erste Pfadsegment haben (z. B. ``DB1/Web``),
    wird es entfernt; Einträge direkt in der Wurzel bekommen die Gruppe ``""``.
    Rückgabe: der entfernte Name oder None.
    """
    firsts = {row["Group"].split("/", 1)[0] for row in rows}
    if len(firsts) != 1:
        return None
    prefix = firsts.pop()
    if not prefix:
        return None
    for row in rows:
        group = row["Group"]
        row["Group"] = group[len(prefix) + 1 :] if group.startswith(prefix + "/") else ""
    return prefix


def parse(text, name, keep_db_name=False):
    """Liest KeePass-CSV-Text. Wirft CsvError, wenn Pflichtspalten fehlen."""
    reader = csv.DictReader(io.StringIO(text, newline=""))
    missing = [c for c in CORE_NAMES if c not in (reader.fieldnames or [])]
    if missing:
        raise CsvError(f"In '{name}' fehlen Spalten: {', '.join(missing)}")
    rows = list(reader)
    prefix = None if keep_db_name else strip_db_prefix(rows)
    notes = [f"Datenbankname „{prefix}“ aus den Gruppenpfaden entfernt."] if prefix else []
    return LoadResult(
        rows=rows,
        format=KEEPASS_CSV,
        provided_columns=frozenset(CORE_NAMES),
        notes=notes,
        db_prefix=prefix,
    )
