"""Einträge: Schlüssel bilden, beschriften und als Papierkorb-Eintrag erkennen.

Ein Eintrag wird durch einen ``Key`` bezeichnet; die Nummer unterscheidet Einträge, die sonst
gleich heißen. Die Zeile dazu ist ein Dict mit allen Spalten (siehe ``columns.py``).
"""

from collections import defaultdict
from typing import NamedTuple

from .columns import KEY_NAMES

# Gruppen, deren Pfad eines dieser Muster enthält, gelten als Papierkorb (Kleinschreibung)
TRASH_PATTERNS = ("papierkorb", "recycle bin")


class Key(NamedTuple):
    group: str
    title: str
    username: str
    number: int = 1  # unterscheidet Einträge mit sonst gleichem Schlüssel

    @property
    def identity(self):
        """Gruppe, Titel und Username ohne die Nummer."""
        return self[:3]


def entries_from_rows(rows):
    """Bildet aus Zeilen ein Dict {Key: Zeile}; doppelte Schlüssel werden nummeriert."""
    seen = defaultdict(int)
    entries = {}
    for row in rows:
        identity = tuple(row[name] for name in KEY_NAMES)
        seen[identity] += 1
        entries[Key(*identity, seen[identity])] = row
    return entries


def entry_label(key):
    """Lesbare Bezeichnung eines Eintrags, z. B. ``Web / Mail  [max]``."""
    text = f"{key.group or '(ohne Gruppe)'} / {key.title or '(ohne Titel)'}"
    if key.username:
        text += f"  [{key.username}]"
    if key.number > 1:
        text += f"  #{key.number}"
    return text


def is_trash(row):
    """Liegt der Eintrag in einer Papierkorb-Gruppe?"""
    group = row["Group"].lower()
    return any(pattern in group for pattern in TRASH_PATTERNS)
