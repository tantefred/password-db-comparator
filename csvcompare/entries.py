"""Einträge: Schlüssel bilden, beschriften und als Papierkorb-Eintrag erkennen.

Ein Eintrag wird durch den Schlüssel ``(Gruppe, Titel, Username, Nummer)`` bezeichnet; die
Nummer unterscheidet Einträge, die sonst gleich heißen. Die Zeile dazu ist ein Dict mit allen
Spalten (siehe ``columns.py``).
"""

from collections import defaultdict

from .columns import KEY_NAMES

# Gruppen, deren Pfad eines dieser Muster enthält, gelten als Papierkorb (Kleinschreibung)
TRASH_PATTERNS = ("papierkorb", "recycle bin")


def entries_from_rows(rows):
    """Bildet aus Zeilen ein Dict {Schlüssel: Zeile}; doppelte Schlüssel werden nummeriert."""
    seen = defaultdict(int)
    entries = {}
    for row in rows:
        base = tuple(row[name] for name in KEY_NAMES)
        seen[base] += 1
        entries[base + (seen[base],)] = row
    return entries


def entry_label(key):
    """Lesbare Bezeichnung eines Eintrags, z. B. ``Web / Mail  [max]``."""
    group, title, username, number = key
    text = f"{group or '(ohne Gruppe)'} / {title or '(ohne Titel)'}"
    if username:
        text += f"  [{username}]"
    if number > 1:
        text += f"  #{number}"
    return text


def is_trash(row):
    """Liegt der Eintrag in einer Papierkorb-Gruppe?"""
    group = row["Group"].lower()
    return any(pattern in group for pattern in TRASH_PATTERNS)
