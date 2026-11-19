"""KeePassium/KeePassXC-CSV: Group, Title, Username, Password, URL, Notes, TOTP, Icon,
Last Modified, Created."""

import csv
import io

from ..constants import EXPECTED
from .base import CsvError, LoadResult

FORMAT = "keepass-csv"


def parse(text, name):
    """Liest KeePass-CSV-Text. Wirft CsvError, wenn Pflichtspalten fehlen."""
    reader = csv.DictReader(io.StringIO(text, newline=""))
    missing = [c for c in EXPECTED if c not in (reader.fieldnames or [])]
    if missing:
        raise CsvError(f"In '{name}' fehlen Spalten: {', '.join(missing)}")
    return LoadResult(rows=list(reader), format=FORMAT, provided_columns=frozenset(EXPECTED))
