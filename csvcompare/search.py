"""Suche nach einem Eintrag über Gruppe, Titel oder Username samt seinem Status."""

from typing import NamedTuple

# Status eines Treffers; ergänzend zu den Aktualitäts-Status aus ``compare``
MOVED, ONLY_IN_OLD, ONLY_IN_NEW, IDENTICAL = "moved", "only_in_old", "only_in_new", "identical"
FOUND = "found"  # Treffer in einer einzelnen Datei (kein Vergleich)


class Hit(NamedTuple):
    status: str  # einer der Status oben oder NEWER_IN_NEW / NEWER_IN_OLD / UNCLEAR
    item: object  # Move bei MOVED, Change bei geänderten, sonst der Schlüssel


def search(cmp, query):
    """Alle Einträge, deren Gruppe/Titel/Username ``query`` enthält, mit Status.

    Ein verschobenes oder umbenanntes Paar erscheint nur einmal, auch wenn beide Schlüssel passen.
    """
    needle = query.strip().lower()
    if cmp.single:
        return [
            Hit(FOUND, key) for key in sorted(cmp.old) if needle in " / ".join(key.identity).lower()
        ]
    only_old, only_new = set(cmp.only_old), set(cmp.only_new)
    move_of = {key: move for move in cmp.moves for key in (move.old_key, move.new_key)}
    change_of = {
        change.key: (freshness, change)
        for freshness, changes in cmp.changes.items()
        for change in changes
    }

    hits, shown_moves = [], set()
    for key in sorted(set(cmp.old) | set(cmp.new)):
        if needle not in " / ".join(key.identity).lower():
            continue
        if key in move_of:
            move = move_of[key]
            if move not in shown_moves:
                shown_moves.add(move)
                hits.append(Hit(MOVED, move))
        elif key in only_old:
            hits.append(Hit(ONLY_IN_OLD, key))
        elif key in only_new:
            hits.append(Hit(ONLY_IN_NEW, key))
        elif key in change_of:
            freshness, change = change_of[key]
            hits.append(Hit(freshness, change))
        else:
            hits.append(Hit(IDENTICAL, key))
    return hits
